from __future__ import annotations

import hashlib
from typing import Any

import pytest

from labreceipt.contracts import RuleSpec
from labreceipt.rules import ArtifactObservation, evaluate


def observation(data: bytes | None, *, state: str = "ok") -> ArtifactObservation:
    digest = None if data is None else f"sha256:{hashlib.sha256(data).hexdigest()}"
    return ArtifactObservation(
        "artifact", "file.txt", state, digest, None if data is None else len(data), data
    )


def rule(rule_type: str, config: dict[str, Any] | None = None) -> RuleSpec:
    return RuleSpec("check", rule_type, "artifact", config or {})


@pytest.mark.parametrize("state", ["missing", "unsafe_path", "too_large", "unreadable"])
def test_exists_fails_for_unavailable_state(state: str) -> None:
    passed, code, details = evaluate(rule("exists"), observation(None, state=state))
    assert not passed
    assert code == "artifact_unavailable"
    assert details == {"state": state}


def test_exists_passes() -> None:
    assert evaluate(rule("exists"), observation(b"x"))[0]


@pytest.mark.parametrize("rule_type", ["utf8", "sha256", "secret_scan", "json_schema"])
def test_content_rules_fail_when_artifact_unavailable(rule_type: str) -> None:
    assert (
        evaluate(rule(rule_type), observation(None, state="missing"))[1] == "artifact_unavailable"
    )


def test_sha256_passes_and_fails() -> None:
    item = observation(b"abc")
    assert evaluate(rule("sha256", {"expected": item.digest}), item)[0]
    assert not evaluate(rule("sha256", {"expected": "sha256:" + "0" * 64}), item)[0]


def test_max_bytes_reports_only_size() -> None:
    result = evaluate(rule("max_bytes", {"limit": 2}), observation(b"abc"))
    assert result == (False, "size_exceeded", {"bytes": 3})


@pytest.mark.parametrize("data", [b"hello", "验收".encode()])
def test_utf8_accepts_text(data: bytes) -> None:
    assert evaluate(rule("utf8"), observation(data))[:2] == (True, "valid_utf8")


def test_utf8_rejects_binary() -> None:
    assert evaluate(rule("utf8"), observation(b"\xff"))[:2] == (False, "invalid_utf8")


def test_text_contains_passes_without_echoing_needle() -> None:
    passed, code, details = evaluate(
        rule("text_contains", {"needle": "needle"}), observation(b"a needle")
    )
    assert (passed, code, details) == (True, "text_found", {})


def test_text_contains_fails() -> None:
    assert (
        evaluate(rule("text_contains", {"needle": "missing"}), observation(b"text"))[1]
        == "text_missing"
    )


@pytest.mark.parametrize(
    ("data", "config", "passed", "lines"),
    [
        (b"", {"min": 0, "max": 0}, True, 0),
        (b"one\n", {"min": 1, "max": 1}, True, 1),
        (b"one\ntwo", {"min": 3, "max": 4}, False, 2),
    ],
)
def test_line_count(data: bytes, config: dict[str, int], passed: bool, lines: int) -> None:
    result = evaluate(rule("line_count", config), observation(data))
    assert result[0] is passed
    assert result[2] == {"lines": lines}


def test_secret_scan_does_not_echo_secret() -> None:
    secret = "ghp_" + "x" * 36
    passed, code, details = evaluate(rule("secret_scan"), observation(secret.encode()))
    assert not passed and code == "secret_found"
    assert secret not in str(details)
    assert details["detectors"] == ["github_token"]


def test_secret_scan_clean() -> None:
    assert evaluate(rule("secret_scan"), observation(b"ordinary"))[0]


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("", {"a": [{"b/c": "ok", "t~n": 2}]}),
        ("/a/0/b~1c", "ok"),
        ("/a/0/t~0n", 2),
    ],
)
def test_json_pointer_equals(pointer: str, expected: Any) -> None:
    data = b'{"a":[{"b/c":"ok","t~n":2}]}'
    assert evaluate(
        rule("json_pointer_equals", {"pointer": pointer, "expected": expected}), observation(data)
    )[0]


@pytest.mark.parametrize("pointer", ["/a/2", "/a/01", "/missing"])
def test_json_pointer_missing(pointer: str) -> None:
    result = evaluate(
        rule("json_pointer_equals", {"pointer": pointer, "expected": 1}), observation(b'{"a":[1]}')
    )
    assert result[:2] == (False, "json_pointer_missing")


def test_json_pointer_value_mismatch() -> None:
    assert (
        evaluate(
            rule("json_pointer_equals", {"pointer": "/x", "expected": 2}), observation(b'{"x":1}')
        )[1]
        == "json_value_mismatch"
    )


@pytest.mark.parametrize(
    ("actual", "expected"),
    [("true", 1), ("false", 0), ("[true]", [1]), ('{"x":true}', {"x": 1})],
)
def test_json_pointer_keeps_booleans_distinct_from_numbers(actual: str, expected: Any) -> None:
    result = evaluate(
        rule("json_pointer_equals", {"pointer": "", "expected": expected}),
        observation(actual.encode()),
    )
    assert result[:2] == (False, "json_value_mismatch")


@pytest.mark.parametrize(("actual", "expected"), [("1", 1.0), ("1.0", 1), ("1e0", 1)])
def test_json_pointer_compares_numbers_by_mathematical_value(
    actual: str, expected: int | float
) -> None:
    assert evaluate(
        rule("json_pointer_equals", {"pointer": "", "expected": expected}),
        observation(actual.encode()),
    )[0]


def test_json_schema_passes() -> None:
    result = evaluate(rule("json_schema", {"schema": {"type": "object"}}), observation(b'{"x":1}'))
    assert result == (True, "schema_valid", {"error_count": 0})


def test_json_schema_counts_errors_without_values() -> None:
    schema = {"type": "object", "required": ["a", "b"]}
    result = evaluate(rule("json_schema", {"schema": schema}), observation(b"{}"))
    assert result == (False, "schema_invalid", {"error_count": 2})


@pytest.mark.parametrize("data", [b"not-json", b'{"a":1,"a":2}'])
def test_json_schema_rejects_invalid_json(data: bytes) -> None:
    assert evaluate(rule("json_schema", {"schema": {}}), observation(data))[1] == "invalid_json"
