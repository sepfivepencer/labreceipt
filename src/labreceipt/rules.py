"""Built-in deterministic acceptance rules."""

from __future__ import annotations

import json
import numbers
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from labreceipt.contracts import RuleSpec, parse_json
from labreceipt.secrets import secret_kinds


@dataclass(frozen=True)
class ArtifactObservation:
    """Content-independent metadata and optional bytes for one artifact."""

    artifact_id: str
    path: str
    state: str
    digest: str | None
    size: int | None
    data: bytes | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "bytes": self.size,
            "id": self.artifact_id,
            "path": self.path,
            "sha256": self.digest,
            "state": self.state,
        }


def _text(observation: ArtifactObservation) -> str | None:
    if observation.data is None:
        return None
    try:
        return observation.data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _json(observation: ArtifactObservation) -> Any:
    if observation.data is None:
        raise ValueError
    try:
        return parse_json(observation.data, label="artifact")
    except Exception as exc:
        raise ValueError from exc


def _pointer(value: Any, pointer: str) -> Any:
    current = value
    if not pointer:
        return current
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise KeyError
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise KeyError
            index = int(token)
            if index >= len(current):
                raise KeyError
            current = current[index]
        else:
            raise KeyError
    return current


def _json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values with booleans distinct and numbers mathematical."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, numbers.Real) and isinstance(right, numbers.Real):
        return left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(a, b) for a, b in zip(left, right, strict=True))
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and left.keys() == right.keys()
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    return False


def evaluate(rule: RuleSpec, observation: ArtifactObservation) -> tuple[bool, str, dict[str, Any]]:
    """Evaluate one rule and return redacted, structured evidence."""
    if rule.rule_type == "exists":
        passed = observation.state == "ok"
        return passed, "present" if passed else "artifact_unavailable", {"state": observation.state}
    if observation.state != "ok" or observation.data is None:
        return False, "artifact_unavailable", {"state": observation.state}

    config = rule.config
    if rule.rule_type == "sha256":
        passed = observation.digest == config["expected"]
        return passed, "digest_match" if passed else "digest_mismatch", {}
    if rule.rule_type == "max_bytes":
        passed = observation.size is not None and observation.size <= config["limit"]
        return passed, "within_limit" if passed else "size_exceeded", {"bytes": observation.size}
    if rule.rule_type == "utf8":
        passed = _text(observation) is not None
        return passed, "valid_utf8" if passed else "invalid_utf8", {}
    if rule.rule_type == "text_contains":
        text = _text(observation)
        if text is None:
            return False, "invalid_utf8", {}
        passed = config["needle"] in text
        return passed, "text_found" if passed else "text_missing", {}
    if rule.rule_type == "line_count":
        text = _text(observation)
        if text is None:
            return False, "invalid_utf8", {}
        count = len(text.splitlines())
        minimum, maximum = config.get("min", 0), config.get("max", 1_000_000)
        passed = minimum <= count <= maximum
        return passed, "line_count_match" if passed else "line_count_mismatch", {"lines": count}
    if rule.rule_type == "secret_scan":
        kinds = secret_kinds(observation.data.decode("utf-8", errors="ignore"))
        passed = not kinds
        return (
            passed,
            "no_secret_found" if passed else "secret_found",
            {
                "detector_count": len(kinds),
                "detectors": list(kinds),
            },
        )
    if rule.rule_type == "json_pointer_equals":
        try:
            actual = _pointer(_json(observation), config["pointer"])
        except (KeyError, ValueError):
            return False, "json_pointer_missing", {}
        passed = _json_equal(actual, config.get("expected"))
        return passed, "json_value_match" if passed else "json_value_mismatch", {}
    if rule.rule_type == "json_schema":
        try:
            instance = _json(observation)
            errors = sum(
                1 for _error in Draft202012Validator(config["schema"]).iter_errors(instance)
            )
        except (ValueError, RecursionError, json.JSONDecodeError):
            return False, "invalid_json", {}
        passed = errors == 0
        return passed, "schema_valid" if passed else "schema_invalid", {"error_count": errors}
    raise AssertionError("validated rule type was not handled")
