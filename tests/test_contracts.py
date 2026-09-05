from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from labreceipt.contracts import contract_from_dict, load_contract, parse_json
from labreceipt.errors import LabReceiptError


def test_valid_contract_round_trips(contract_dict: dict[str, Any]) -> None:
    contract = contract_from_dict(contract_dict)
    assert contract_from_dict(contract.to_dict()) == contract
    assert contract.digest.startswith("sha256:")


def test_valid_model_candidate(contract_dict: dict[str, Any]) -> None:
    contract_dict["status"] = "candidate"
    contract_dict.pop("reviewed_by")
    contract_dict["proposal"] = {
        "kind": "model",
        "provider": "openai-compatible",
        "model": "qwen2.5:7b",
    }
    contract = contract_from_dict(contract_dict)
    assert contract.proposal == {
        "kind": "model",
        "provider": "openai-compatible",
        "model": "qwen2.5:7b",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("contract_id", "Bad ID"),
        ("status", "approved"),
    ],
)
def test_rejects_invalid_top_level_values(
    contract_dict: dict[str, Any], field: str, value: object
) -> None:
    contract_dict[field] = value
    with pytest.raises(LabReceiptError):
        contract_from_dict(contract_dict)


def test_rejects_unknown_top_level_field(contract_dict: dict[str, Any]) -> None:
    contract_dict["surprise"] = True
    with pytest.raises(LabReceiptError, match="unsupported"):
        contract_from_dict(contract_dict)


def test_candidate_cannot_claim_reviewer(contract_dict: dict[str, Any]) -> None:
    contract_dict["status"] = "candidate"
    with pytest.raises(LabReceiptError, match="cannot claim"):
        contract_from_dict(contract_dict)


def test_confirmed_requires_reviewer(contract_dict: dict[str, Any]) -> None:
    contract_dict.pop("reviewed_by")
    with pytest.raises(LabReceiptError, match="require"):
        contract_from_dict(contract_dict)


@pytest.mark.parametrize("reviewer", ["Alice", "a b", "_alice", "a" * 65])
def test_rejects_unsafe_reviewer(contract_dict: dict[str, Any], reviewer: str) -> None:
    contract_dict["reviewed_by"] = reviewer
    with pytest.raises(LabReceiptError, match="reviewer"):
        contract_from_dict(contract_dict)


def test_rejects_empty_artifacts(contract_dict: dict[str, Any]) -> None:
    contract_dict["artifacts"] = []
    with pytest.raises(LabReceiptError, match="artifact list"):
        contract_from_dict(contract_dict)


def test_rejects_empty_rules(contract_dict: dict[str, Any]) -> None:
    contract_dict["rules"] = []
    with pytest.raises(LabReceiptError, match="rule list"):
        contract_from_dict(contract_dict)


def test_rejects_duplicate_artifact_id(contract_dict: dict[str, Any]) -> None:
    contract_dict["artifacts"][1]["id"] = "source"
    contract_dict["artifacts"][1]["depends_on"] = []
    with pytest.raises(LabReceiptError, match="ids must be unique"):
        contract_from_dict(contract_dict)


def test_rejects_duplicate_artifact_path(contract_dict: dict[str, Any]) -> None:
    contract_dict["artifacts"][1]["path"] = "source.txt"
    with pytest.raises(LabReceiptError, match="paths must be unique"):
        contract_from_dict(contract_dict)


def test_rejects_duplicate_rule_id(contract_dict: dict[str, Any]) -> None:
    contract_dict["rules"][1]["id"] = "source_exists"
    with pytest.raises(LabReceiptError, match="rule ids"):
        contract_from_dict(contract_dict)


def test_rejects_self_dependency(contract_dict: dict[str, Any]) -> None:
    contract_dict["artifacts"][0]["depends_on"] = ["source"]
    with pytest.raises(LabReceiptError, match="cannot reference themselves"):
        contract_from_dict(contract_dict)


def test_rejects_unknown_dependency(contract_dict: dict[str, Any]) -> None:
    contract_dict["artifacts"][1]["depends_on"] = ["missing"]
    with pytest.raises(LabReceiptError, match="unknown artifact"):
        contract_from_dict(contract_dict)


def test_rejects_dependency_cycle(contract_dict: dict[str, Any]) -> None:
    contract_dict["artifacts"][0]["depends_on"] = ["report"]
    with pytest.raises(LabReceiptError, match="cycle"):
        contract_from_dict(contract_dict)


def test_rejects_unknown_rule_artifact(contract_dict: dict[str, Any]) -> None:
    contract_dict["rules"][0]["artifact"] = "missing"
    with pytest.raises(LabReceiptError, match="unknown artifact"):
        contract_from_dict(contract_dict)


def test_rejects_unknown_rule_type(contract_dict: dict[str, Any]) -> None:
    contract_dict["rules"][0]["type"] = "shell"
    with pytest.raises(LabReceiptError, match="not supported"):
        contract_from_dict(contract_dict)


@pytest.mark.parametrize("maximum", [0, -1, 16_777_217, 1.5, True])
def test_rejects_invalid_artifact_size(contract_dict: dict[str, Any], maximum: object) -> None:
    contract_dict["artifacts"][0]["max_bytes"] = maximum
    with pytest.raises(LabReceiptError, match="max_bytes"):
        contract_from_dict(contract_dict)


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "a\\b", ""])
def test_rejects_unsafe_artifact_path(contract_dict: dict[str, Any], path: str) -> None:
    contract_dict["artifacts"][0]["path"] = path
    with pytest.raises(LabReceiptError, match="path"):
        contract_from_dict(contract_dict)


@pytest.mark.parametrize(
    ("rule_type", "config"),
    [
        ("exists", {"extra": True}),
        ("sha256", {"expected": "abc"}),
        ("max_bytes", {"limit": -1}),
        ("text_contains", {"needle": ""}),
        ("line_count", {"min": 3, "max": 2}),
        ("json_pointer_equals", {"pointer": "no-slash", "expected": 1}),
        ("json_pointer_equals", {"pointer": "/bad~2escape", "expected": 1}),
        ("json_schema", {"schema": "not-object"}),
    ],
)
def test_rejects_bad_rule_configs(
    contract_dict: dict[str, Any], rule_type: str, config: dict[str, Any]
) -> None:
    contract_dict["rules"][0]["type"] = rule_type
    contract_dict["rules"][0]["config"] = config
    with pytest.raises(LabReceiptError):
        contract_from_dict(contract_dict)


def test_rejects_invalid_json_schema(contract_dict: dict[str, Any]) -> None:
    contract_dict["rules"][2]["config"] = {"schema": {"type": 4}}
    with pytest.raises(LabReceiptError, match="invalid"):
        contract_from_dict(contract_dict)


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_rejects_remote_json_schema_reference(contract_dict: dict[str, Any], keyword: str) -> None:
    contract_dict["rules"][2]["config"] = {"schema": {keyword: "https://example.test/schema.json"}}
    with pytest.raises(LabReceiptError, match="disabled"):
        contract_from_dict(contract_dict)


def test_rejects_local_json_schema_reference(contract_dict: dict[str, Any]) -> None:
    contract_dict["rules"][2]["config"] = {
        "schema": {"$defs": {"x": {"type": "object"}}, "$ref": "#/$defs/x"}
    }
    with pytest.raises(LabReceiptError, match="disabled"):
        contract_from_dict(contract_dict)


@pytest.mark.parametrize("keyword", ["pattern", "patternProperties"])
def test_rejects_regex_json_schema_keywords(contract_dict: dict[str, Any], keyword: str) -> None:
    contract_dict["rules"][2]["config"] = {
        "schema": {keyword: "a+" if keyword == "pattern" else {"a+": {"type": "string"}}}
    }
    with pytest.raises(LabReceiptError, match="disabled"):
        contract_from_dict(contract_dict)


def test_rejects_secret_in_contract_metadata(contract_dict: dict[str, Any]) -> None:
    secret = "ghp_" + "s" * 36
    contract_dict["rules"][0] = {
        "id": "contains",
        "type": "text_contains",
        "artifact": "source",
        "config": {"needle": secret},
    }
    with pytest.raises(LabReceiptError, match="recognized secret") as error:
        contract_from_dict(contract_dict)
    assert secret not in str(error.value)


def test_parse_json_rejects_duplicate_key() -> None:
    with pytest.raises(LabReceiptError, match="duplicate"):
        parse_json(b'{"a":1,"a":2}', label="test")


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_parse_json_rejects_nonfinite_number(constant: bytes) -> None:
    with pytest.raises(LabReceiptError, match="non-finite"):
        parse_json(constant, label="test")


def test_parse_json_rejects_oversized_integer_without_value_error() -> None:
    with pytest.raises(LabReceiptError, match="digit limit"):
        parse_json(("1" * 5001).encode(), label="test")


@pytest.mark.parametrize(
    "payload",
    [b'"\\ud800"', b'"\\udfff"', b'{"\\ud800":1}', b'{"key":"\\udc00"}'],
)
def test_parse_json_rejects_unpaired_surrogate(payload: bytes) -> None:
    with pytest.raises(LabReceiptError, match="unpaired"):
        parse_json(payload, label="test")


def test_parse_json_normalizes_paired_surrogate() -> None:
    assert parse_json(b'"\\ud83d\\ude00"', label="test") == "😀"


def test_contract_rejects_unpaired_surrogate_path(contract_dict: dict[str, Any]) -> None:
    contract_dict["artifacts"][0]["path"] = "bad\ud800.txt"
    with pytest.raises(LabReceiptError, match="unpaired"):
        contract_from_dict(contract_dict)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_direct_contract_rejects_nonfinite_number(
    contract_dict: dict[str, Any], number: float
) -> None:
    contract_dict["rules"][0] = {
        "id": "value",
        "type": "json_pointer_equals",
        "artifact": "source",
        "config": {"pointer": "", "expected": number},
    }
    with pytest.raises(LabReceiptError, match="non-finite"):
        contract_from_dict(contract_dict)


def test_parse_json_rejects_invalid_utf8() -> None:
    with pytest.raises(LabReceiptError, match="UTF-8"):
        parse_json(b"\xff", label="test")


def test_load_contract_reads_valid_file(contract_dict: dict[str, Any], tmp_path: Path) -> None:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract_dict), encoding="utf-8")
    assert load_contract(path).contract_id == "demo"


def test_contract_digest_changes_with_rule(contract_dict: dict[str, Any]) -> None:
    first = contract_from_dict(contract_dict).digest
    changed = copy.deepcopy(contract_dict)
    changed["rules"][1]["id"] = "different"
    assert contract_from_dict(changed).digest != first
