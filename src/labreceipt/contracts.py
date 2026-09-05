"""Contract parsing and validation."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from labreceipt.canonical import canonical_bytes, digest_json, normalize_json_unicode
from labreceipt.errors import LabReceiptError
from labreceipt.safeio import read_user_file, validate_relative_path
from labreceipt.secrets import metadata_secret_kinds

MAX_CONTRACT_BYTES = 1_048_576
MAX_ARTIFACTS = 256
MAX_RULES = 1024
MAX_ARTIFACT_BYTES = 16_777_216
MAX_INTEGER_DIGITS = 1024
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ALLOWED_RULES = {
    "exists",
    "json_schema",
    "json_pointer_equals",
    "line_count",
    "max_bytes",
    "secret_scan",
    "sha256",
    "text_contains",
    "utf8",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LabReceiptError("JSON contains a duplicate object key")
        result[key] = value
    return result


def parse_json(data: bytes, *, label: str) -> Any:
    """Parse bounded UTF-8 JSON while rejecting duplicate keys and NaN."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LabReceiptError(f"{label} must be UTF-8 JSON") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_bounded_integer,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                LabReceiptError(f"{label} contains a non-finite number")
            ),
        )
    except LabReceiptError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise LabReceiptError(f"{label} is not valid JSON") from exc
    except ValueError as exc:
        raise LabReceiptError(f"{label} contains an invalid or oversized number") from exc
    return normalize_json_unicode(value)


def _bounded_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > MAX_INTEGER_DIGITS:
        raise LabReceiptError("JSON integer exceeds the digit limit")
    return int(value)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise LabReceiptError(f"{field} must match the safe identifier format")
    return value


def _label(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _LABEL.fullmatch(value):
        raise LabReceiptError(f"{field} must match the safe label format")
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    if set(value) - allowed:
        raise LabReceiptError(f"{label} contains an unsupported field")


def _bounded_json(value: Any, *, max_nodes: int = 4096, max_depth: int = 32) -> None:
    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise LabReceiptError("nested JSON exceeds the safety limit")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise LabReceiptError("JSON object keys must be strings")
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        elif item is not None:
            if not isinstance(item, (str, int, float, bool)):
                raise LabReceiptError("contract contains a non-JSON value")
            if isinstance(item, float) and not math.isfinite(item):
                raise LabReceiptError("contract contains a non-finite number")

    walk(value, 0)


def _reject_unsafe_schema_features(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef", "pattern", "patternProperties"}:
                raise LabReceiptError("JSON Schema references and regular expressions are disabled")
            _reject_unsafe_schema_features(child)
    elif isinstance(value, list):
        for child in value:
            _reject_unsafe_schema_features(child)


@dataclass(frozen=True)
class ArtifactSpec:
    """One file expected in the workspace."""

    artifact_id: str
    path: str
    depends_on: tuple[str, ...]
    max_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "depends_on": list(self.depends_on),
            "id": self.artifact_id,
            "max_bytes": self.max_bytes,
            "path": self.path,
        }


@dataclass(frozen=True)
class RuleSpec:
    """A built-in deterministic check over one artifact."""

    rule_id: str
    rule_type: str
    artifact_id: str
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact_id,
            "config": self.config,
            "id": self.rule_id,
            "type": self.rule_type,
        }


@dataclass(frozen=True)
class Contract:
    """A validated candidate or human-confirmed acceptance contract."""

    contract_id: str
    status: str
    artifacts: tuple[ArtifactSpec, ...]
    rules: tuple[RuleSpec, ...]
    reviewed_by: str | None = None
    proposal: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "contract_id": self.contract_id,
            "rules": [rule.to_dict() for rule in self.rules],
            "schema_version": "1",
            "status": self.status,
        }
        if self.reviewed_by is not None:
            value["reviewed_by"] = self.reviewed_by
        if self.proposal is not None:
            value["proposal"] = dict(sorted(self.proposal.items()))
        return value

    @property
    def digest(self) -> str:
        return digest_json(self.to_dict())


def _parse_artifact(value: Any) -> ArtifactSpec:
    if not isinstance(value, dict):
        raise LabReceiptError("each artifact must be an object")
    _exact_keys(value, {"id", "path", "depends_on", "max_bytes"}, "artifact")
    artifact_id = _identifier(value.get("id"), "artifact id")
    path = value.get("path")
    if not isinstance(path, str):
        raise LabReceiptError("artifact path must be a string")
    validate_relative_path(path)
    dependencies = value.get("depends_on", [])
    if not isinstance(dependencies, list) or len(dependencies) > MAX_ARTIFACTS:
        raise LabReceiptError("artifact dependencies must be a bounded list")
    parsed_dependencies = tuple(_identifier(item, "dependency id") for item in dependencies)
    if (
        len(set(parsed_dependencies)) != len(parsed_dependencies)
        or artifact_id in parsed_dependencies
    ):
        raise LabReceiptError(
            "artifact dependencies must be unique and cannot reference themselves"
        )
    max_bytes = value.get("max_bytes", 1_048_576)
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_ARTIFACT_BYTES:
        raise LabReceiptError("artifact max_bytes is outside the safety limit")
    return ArtifactSpec(artifact_id, path, parsed_dependencies, max_bytes)


def _validate_rule_config(rule_type: str, config: dict[str, Any]) -> None:
    if rule_type in {"exists", "secret_scan", "utf8"}:
        _exact_keys(config, set(), "rule config")
    elif rule_type == "sha256":
        _exact_keys(config, {"expected"}, "sha256 config")
        if not isinstance(config.get("expected"), str) or not _SHA256.fullmatch(config["expected"]):
            raise LabReceiptError("sha256 rule requires a prefixed lowercase digest")
    elif rule_type == "max_bytes":
        _exact_keys(config, {"limit"}, "max_bytes config")
        limit = config.get("limit")
        if type(limit) is not int or not 0 <= limit <= MAX_ARTIFACT_BYTES:
            raise LabReceiptError("max_bytes rule limit is outside the safety limit")
    elif rule_type == "text_contains":
        _exact_keys(config, {"needle"}, "text_contains config")
        needle = config.get("needle")
        if not isinstance(needle, str) or not needle or len(needle.encode("utf-8")) > 256:
            raise LabReceiptError("text_contains needle must be 1 to 256 UTF-8 bytes")
    elif rule_type == "line_count":
        _exact_keys(config, {"min", "max"}, "line_count config")
        minimum, maximum = config.get("min", 0), config.get("max", 1_000_000)
        if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum:
            raise LabReceiptError("line_count bounds are invalid")
    elif rule_type == "json_pointer_equals":
        _exact_keys(config, {"pointer", "expected"}, "json_pointer_equals config")
        pointer = config.get("pointer")
        if (
            not isinstance(pointer, str)
            or (pointer and not pointer.startswith("/"))
            or len(pointer) > 512
        ):
            raise LabReceiptError("JSON pointer is invalid or too long")
        if re.search(r"~(?:[^01]|$)", pointer):
            raise LabReceiptError("JSON pointer contains an invalid escape")
        _bounded_json(config.get("expected"), max_nodes=256, max_depth=16)
    elif rule_type == "json_schema":
        _exact_keys(config, {"schema"}, "json_schema config")
        schema = config.get("schema")
        if not isinstance(schema, (dict, bool)):
            raise LabReceiptError("json_schema rule requires an inline schema")
        _bounded_json(schema)
        if len(canonical_bytes(schema)) > 131_072:
            raise LabReceiptError("inline JSON Schema exceeds the size limit")
        _reject_unsafe_schema_features(schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise LabReceiptError("inline JSON Schema is invalid") from exc


def _parse_rule(value: Any) -> RuleSpec:
    if not isinstance(value, dict):
        raise LabReceiptError("each rule must be an object")
    _exact_keys(value, {"id", "type", "artifact", "config"}, "rule")
    rule_id = _identifier(value.get("id"), "rule id")
    rule_type = value.get("type")
    if not isinstance(rule_type, str) or rule_type not in _ALLOWED_RULES:
        raise LabReceiptError("rule type is not supported")
    artifact_id = _identifier(value.get("artifact"), "rule artifact id")
    config = value.get("config", {})
    if not isinstance(config, dict):
        raise LabReceiptError("rule config must be an object")
    _validate_rule_config(rule_type, config)
    return RuleSpec(rule_id, rule_type, artifact_id, config)


def _check_graph(artifacts: Iterable[ArtifactSpec]) -> None:
    by_id = {artifact.artifact_id: artifact for artifact in artifacts}
    for artifact in by_id.values():
        if any(dependency not in by_id for dependency in artifact.depends_on):
            raise LabReceiptError("artifact dependency references an unknown artifact")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(artifact_id: str) -> None:
        if artifact_id in visiting:
            raise LabReceiptError("artifact dependency graph contains a cycle")
        if artifact_id in visited:
            return
        visiting.add(artifact_id)
        for dependency in by_id[artifact_id].depends_on:
            visit(dependency)
        visiting.remove(artifact_id)
        visited.add(artifact_id)

    for artifact_id in by_id:
        visit(artifact_id)


def contract_from_dict(value: Any) -> Contract:
    """Validate a decoded contract and return its typed form."""
    value = normalize_json_unicode(value)
    if not isinstance(value, dict):
        raise LabReceiptError("contract must be a JSON object")
    _bounded_json(value)
    _exact_keys(
        value,
        {
            "schema_version",
            "contract_id",
            "status",
            "reviewed_by",
            "proposal",
            "artifacts",
            "rules",
        },
        "contract",
    )
    if value.get("schema_version") != "1":
        raise LabReceiptError("contract schema_version must be 1")
    contract_id = _identifier(value.get("contract_id"), "contract id")
    status = value.get("status")
    if status not in {"candidate", "confirmed"}:
        raise LabReceiptError("contract status must be candidate or confirmed")
    reviewed_by_value = value.get("reviewed_by")
    reviewed_by = (
        None if reviewed_by_value is None else _identifier(reviewed_by_value, "reviewer id")
    )
    if status == "candidate" and reviewed_by is not None:
        raise LabReceiptError("candidate contracts cannot claim a human reviewer")
    if status == "confirmed" and reviewed_by is None:
        raise LabReceiptError("confirmed contracts require a reviewer id")
    proposal_value = value.get("proposal")
    proposal: dict[str, str] | None = None
    if proposal_value is not None:
        if not isinstance(proposal_value, dict):
            raise LabReceiptError("proposal provenance must be an object")
        _exact_keys(proposal_value, {"kind", "provider", "model"}, "proposal provenance")
        if proposal_value.get("kind") != "model":
            raise LabReceiptError("proposal provenance kind must be model")
        provider = _label(proposal_value.get("provider"), "proposal provider")
        model = _label(proposal_value.get("model"), "proposal model")
        proposal = {"kind": "model", "provider": provider, "model": model}
    artifacts_value = value.get("artifacts")
    rules_value = value.get("rules")
    if not isinstance(artifacts_value, list) or not 1 <= len(artifacts_value) <= MAX_ARTIFACTS:
        raise LabReceiptError("contract requires a bounded non-empty artifact list")
    if not isinstance(rules_value, list) or not 1 <= len(rules_value) <= MAX_RULES:
        raise LabReceiptError("contract requires a bounded non-empty rule list")
    artifacts = tuple(_parse_artifact(item) for item in artifacts_value)
    rules = tuple(_parse_rule(item) for item in rules_value)
    artifact_ids = [item.artifact_id for item in artifacts]
    rule_ids = [item.rule_id for item in rules]
    if len(set(artifact_ids)) != len(artifact_ids):
        raise LabReceiptError("artifact ids must be unique")
    if len(set(rule_ids)) != len(rule_ids):
        raise LabReceiptError("rule ids must be unique")
    paths = [item.path for item in artifacts]
    if len(set(paths)) != len(paths):
        raise LabReceiptError("artifact paths must be unique")
    if any(rule.artifact_id not in set(artifact_ids) for rule in rules):
        raise LabReceiptError("rule references an unknown artifact")
    _check_graph(artifacts)
    if metadata_secret_kinds(value):
        raise LabReceiptError("contract metadata contains a recognized secret")
    return Contract(contract_id, status, artifacts, rules, reviewed_by, proposal)


def load_contract(path: Path) -> Contract:
    """Load and validate a contract from disk."""
    data = read_user_file(path, MAX_CONTRACT_BYTES)
    return contract_from_dict(parse_json(data, label="contract"))
