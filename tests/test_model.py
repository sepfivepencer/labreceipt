from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from labreceipt.contracts import contract_from_dict
from labreceipt.errors import LabReceiptError
from labreceipt.model import (
    _candidate_from_response,
    _NoRedirect,
    _validate_endpoint,
    confirm_contract,
    propose_contract,
)


def proposal_content() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "contract_id": "model_candidate",
        "status": "confirmed",
        "reviewed_by": "model",
        "artifacts": [{"id": "report", "path": "report.txt", "depends_on": [], "max_bytes": 1000}],
        "rules": [{"id": "exists", "type": "exists", "artifact": "report", "config": {}}],
    }


def response_bytes(content: Any) -> bytes:
    return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://models.example/v1/chat/completions",
        "http://localhost:8000/v1/chat/completions",
        "http://127.0.0.1:9000/v1/chat/completions",
        "http://[::1]:8000/v1/chat/completions",
    ],
)
def test_accepts_safe_model_endpoints(endpoint: str) -> None:
    _validate_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///tmp/model",
        "http://example.test/model",
        "https://user:pass@example.test/model",
        "https://example.test/model?q=1",
        "https://example.test/model#fragment",
        "https://example.test:bad/model",
        "https://example.test/model\nheader",
        "not-a-url",
    ],
)
def test_rejects_unsafe_model_endpoint(endpoint: str) -> None:
    with pytest.raises(LabReceiptError):
        _validate_endpoint(endpoint)


def test_candidate_response_is_forced_to_unconfirmed() -> None:
    candidate = _candidate_from_response(response_bytes(proposal_content()), "qwen2.5:7b")
    assert candidate.status == "candidate"
    assert candidate.reviewed_by is None
    assert candidate.proposal == {
        "kind": "model",
        "provider": "openai-compatible",
        "model": "qwen2.5:7b",
    }


@pytest.mark.parametrize(
    "payload",
    [b"{}", b'{"choices":[]}', b'{"choices":[{"message":{"content":4}}]}'],
)
def test_rejects_missing_model_content(payload: bytes) -> None:
    with pytest.raises(LabReceiptError, match="content"):
        _candidate_from_response(payload, "model")


def test_rejects_unpaired_surrogate_in_model_content() -> None:
    payload = b'{"choices":[{"message":{"content":"\\ud800"}}]}'
    with pytest.raises(LabReceiptError, match="unpaired"):
        _candidate_from_response(payload, "model")


def test_rejects_model_shell_rule() -> None:
    content = proposal_content()
    content["rules"][0]["type"] = "shell"
    with pytest.raises(LabReceiptError, match="not supported"):
        _candidate_from_response(response_bytes(content), "model")


def test_confirm_contract_records_explicit_reviewer() -> None:
    value = proposal_content()
    value["status"] = "candidate"
    value.pop("reviewed_by")
    candidate = contract_from_dict(value)
    confirmed = confirm_contract(candidate, "alice")
    assert confirmed.status == "confirmed"
    assert confirmed.reviewed_by == "alice"


def test_cannot_confirm_confirmed_contract(contract_dict: dict[str, Any]) -> None:
    with pytest.raises(LabReceiptError, match="only a candidate"):
        confirm_contract(contract_from_dict(contract_dict), "alice")


def test_propose_is_offline_by_default(tmp_path: Path) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("write a report")
    with pytest.raises(LabReceiptError, match="disabled"):
        propose_contract(
            brief,
            endpoint="https://example.test/v1/chat/completions",
            model="model",
            allow_network=False,
        )


def test_propose_cancels_secret_brief(tmp_path: Path) -> None:
    brief = tmp_path / "brief.txt"
    secret = "ghp_" + "x" * 36
    brief.write_text(f"use {secret}")
    with pytest.raises(LabReceiptError, match="cancelled") as error:
        propose_contract(
            brief,
            endpoint="https://example.test/v1/chat/completions",
            model="model",
            allow_network=True,
        )
    assert secret not in str(error.value)


@pytest.mark.parametrize("timeout", [0.0, 30.1])
def test_propose_rejects_unsafe_timeout(tmp_path: Path, timeout: float) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("safe")
    with pytest.raises(LabReceiptError, match="timeout"):
        propose_contract(
            brief,
            endpoint="https://example.test/v1/chat/completions",
            model="model",
            allow_network=True,
            timeout=timeout,
        )


@pytest.mark.parametrize("env_name", ["HOME", "lower_API_KEY", "9TOKEN"])
def test_propose_rejects_unsafe_key_environment_name(tmp_path: Path, env_name: str) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("safe")
    with pytest.raises(LabReceiptError, match="environment"):
        propose_contract(
            brief,
            endpoint="https://example.test/v1/chat/completions",
            model="model",
            allow_network=True,
            api_key_env=env_name,
        )


def test_propose_rejects_secret_as_model_name(tmp_path: Path) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("safe")
    with pytest.raises(LabReceiptError, match="model name"):
        propose_contract(
            brief,
            endpoint="https://example.test/v1/chat/completions",
            model="sk-" + "x" * 24,
            allow_network=True,
        )


class FakeResponse:
    def __init__(self, data: bytes, *, status: int = 200, length: str | None = None) -> None:
        self.data = data
        self.status = status
        self.headers = {} if length is None else {"Content-Length": length}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.data[:limit]


class FakeOpener:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.request: urllib.request.Request | None = None

    def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.request = request
        if isinstance(self.response, Exception):
            raise self.response
        assert timeout > 0
        return self.response


def test_propose_calls_opted_in_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("Deliver report.txt with a conclusion")
    opener = FakeOpener(FakeResponse(response_bytes(proposal_content())))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)
    monkeypatch.setenv("LABRECEIPT_API_KEY", "test-only-key")
    candidate = propose_contract(
        brief,
        endpoint="https://example.test/v1/chat/completions",
        model="model-v1",
        allow_network=True,
    )
    assert candidate.status == "candidate"
    assert opener.request is not None
    assert opener.request.get_header("Authorization") == "Bearer test-only-key"


def test_propose_suppresses_network_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    brief = tmp_path / "brief.txt"
    brief.write_text("safe")
    network_error = urllib.error.URLError("upstream included private details")
    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *_handlers: FakeOpener(network_error)
    )
    with pytest.raises(LabReceiptError, match="details were suppressed") as error:
        propose_contract(
            brief,
            endpoint="https://example.test/v1/chat/completions",
            model="model",
            allow_network=True,
        )
    assert "private details" not in str(error.value)


def test_no_redirect_handler_refuses_redirect() -> None:
    handler = _NoRedirect()
    assert (
        handler.redirect_request(  # type: ignore[func-returns-value]
            urllib.request.Request("https://example.test"),
            None,
            302,
            "moved",
            {},
            "https://other.test",
        )
        is None
    )
