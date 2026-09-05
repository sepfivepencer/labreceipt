"""Evidence receipt construction and verification."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from labreceipt.canonical import canonical_bytes, digest_json
from labreceipt.contracts import parse_json
from labreceipt.errors import LabReceiptError
from labreceipt.safeio import read_user_file
from labreceipt.secrets import metadata_secret_kinds

MAX_RECEIPT_BYTES = 4_194_304


def seal_receipt(body: dict[str, Any]) -> dict[str, Any]:
    """Add a deterministic self-digest to a receipt body."""
    return {"receipt_id": digest_json(body), **body}


def receipt_bytes(receipt: dict[str, Any]) -> bytes:
    """Return canonical receipt bytes followed by one newline."""
    return canonical_bytes(receipt) + b"\n"


def load_receipt(path: Path) -> dict[str, Any]:
    """Load a prior receipt and verify its self-digest and safe shape."""
    value = parse_json(read_user_file(path, MAX_RECEIPT_BYTES), label="receipt")
    if not isinstance(value, dict):
        raise LabReceiptError("receipt must be a JSON object")
    receipt_id = value.get("receipt_id")
    if not isinstance(receipt_id, str):
        raise LabReceiptError("receipt id is missing")
    body = {key: item for key, item in value.items() if key != "receipt_id"}
    if digest_json(body) != receipt_id:
        raise LabReceiptError("receipt self-digest does not match its content")
    if value.get("schema_version") != "1":
        raise LabReceiptError("receipt schema version is unsupported")
    if metadata_secret_kinds(value):
        raise LabReceiptError("receipt contains a recognized secret")
    for field in ("contract", "engine", "artifacts", "evidence", "summary", "impact"):
        if field not in value:
            raise LabReceiptError("receipt is missing a required field")
    if not isinstance(value["artifacts"], list) or not isinstance(value["evidence"], list):
        raise LabReceiptError("receipt lists are malformed")
    return value
