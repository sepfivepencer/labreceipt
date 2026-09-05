"""Optional, explicitly enabled OpenAI-compatible contract proposal adapter."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from labreceipt.contracts import Contract, contract_from_dict, parse_json
from labreceipt.errors import LabReceiptError
from labreceipt.safeio import read_user_file
from labreceipt.secrets import secret_kinds

MAX_BRIEF_BYTES = 65_536
MAX_RESPONSE_BYTES = 524_288
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MODEL_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _validate_endpoint(endpoint: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in endpoint):
        raise LabReceiptError("model endpoint contains a control character")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LabReceiptError("model endpoint must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise LabReceiptError("model endpoint cannot contain credentials, query, or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise LabReceiptError("unencrypted model endpoints are limited to loopback hosts")
    try:
        parsed.port
    except ValueError as exc:
        raise LabReceiptError("model endpoint port is invalid") from exc


def _read_response(response: Any) -> bytes:
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            if int(length) > MAX_RESPONSE_BYTES:
                raise LabReceiptError("model response exceeds the size limit")
        except ValueError as exc:
            raise LabReceiptError("model response has an invalid content length") from exc
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if not isinstance(data, bytes):
        raise LabReceiptError("model response body is not bytes")
    if len(data) > MAX_RESPONSE_BYTES:
        raise LabReceiptError("model response exceeds the size limit")
    return data


def _candidate_from_response(data: bytes, model: str) -> Contract:
    envelope = parse_json(data, label="model response")
    try:
        content = envelope["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LabReceiptError("model response lacks chat completion content") from exc
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise LabReceiptError("model response content must be bounded JSON text")
    proposed = parse_json(content.encode("utf-8"), label="model contract proposal")
    if not isinstance(proposed, dict):
        raise LabReceiptError("model contract proposal must be a JSON object")
    proposed["schema_version"] = "1"
    proposed["status"] = "candidate"
    proposed.pop("reviewed_by", None)
    proposed["proposal"] = {
        "kind": "model",
        "model": model,
        "provider": "openai-compatible",
    }
    return contract_from_dict(proposed)


def propose_contract(
    brief_path: Path,
    *,
    endpoint: str,
    model: str,
    allow_network: bool,
    api_key_env: str = "LABRECEIPT_API_KEY",
    timeout: float = 10.0,
) -> Contract:
    """Ask a configured model for an unconfirmed contract candidate."""
    if not allow_network:
        raise LabReceiptError("model access is disabled; pass --allow-network to opt in")
    _validate_endpoint(endpoint)
    if not _MODEL_LABEL.fullmatch(model) or secret_kinds(model):
        raise LabReceiptError("model name must match the safe label format")
    if not _ENV_NAME.fullmatch(api_key_env) or not api_key_env.endswith(("_API_KEY", "_TOKEN")):
        raise LabReceiptError("API key environment variable name is invalid")
    if not 0.1 <= timeout <= 30.0:
        raise LabReceiptError("model timeout must be between 0.1 and 30 seconds")
    brief_data = read_user_file(brief_path, MAX_BRIEF_BYTES)
    try:
        brief = brief_data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LabReceiptError("task brief must be UTF-8 text") from exc
    if secret_kinds(brief):
        raise LabReceiptError("task brief contains a recognized secret; model call cancelled")
    system = (
        "Return exactly one JSON object for a LabReceipt candidate contract. "
        "Use schema_version 1, a safe lowercase contract_id, status candidate, one or more "
        "artifacts with id/path/depends_on/max_bytes, and built-in rules only: exists, sha256, "
        "max_bytes, utf8, text_contains, line_count, json_schema, json_pointer_equals, secret_scan. "
        "Do not include shell commands, URLs, credentials, reviewed_by, prose, or code fences."
    )
    payload = json.dumps(
        {
            "messages": [
                {"content": system, "role": "system"},
                {"content": brief, "role": "user"},
            ],
            "model": model,
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(api_key_env)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            if getattr(response, "status", 200) != 200:
                raise LabReceiptError("model endpoint returned a non-success status")
            data = _read_response(response)
    except LabReceiptError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LabReceiptError("model request failed; response details were suppressed") from exc
    return _candidate_from_response(data, model)


def confirm_contract(candidate: Contract, reviewed_by: str) -> Contract:
    """Turn a candidate into a confirmed contract after an explicit human action."""
    if candidate.status != "candidate":
        raise LabReceiptError("only a candidate contract can be confirmed")
    value = candidate.to_dict()
    value["status"] = "confirmed"
    value["reviewed_by"] = reviewed_by
    return contract_from_dict(value)
