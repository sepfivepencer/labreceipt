"""Canonical JSON and deterministic digest helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from labreceipt.errors import LabReceiptError


def normalize_text(value: str) -> str:
    """Combine valid surrogate pairs and reject unpaired surrogates."""
    result: list[str] = []
    index = 0
    while index < len(value):
        codepoint = ord(value[index])
        if 0xD800 <= codepoint <= 0xDBFF:
            if index + 1 >= len(value):
                raise LabReceiptError("JSON text contains an unpaired Unicode surrogate")
            following = ord(value[index + 1])
            if not 0xDC00 <= following <= 0xDFFF:
                raise LabReceiptError("JSON text contains an unpaired Unicode surrogate")
            combined = 0x10000 + ((codepoint - 0xD800) << 10) + (following - 0xDC00)
            result.append(chr(combined))
            index += 2
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            raise LabReceiptError("JSON text contains an unpaired Unicode surrogate")
        result.append(value[index])
        index += 1
    return "".join(result)


def normalize_json_unicode(value: Any) -> Any:
    """Normalize every JSON string and object key without exposing bad text."""
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, list):
        return [normalize_json_unicode(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise LabReceiptError("JSON object keys must be strings")
            normalized_key = normalize_text(key)
            if normalized_key in normalized:
                raise LabReceiptError("JSON contains a duplicate key after Unicode normalization")
            normalized[normalized_key] = normalize_json_unicode(item)
        return normalized
    return value


def canonical_bytes(value: Any) -> bytes:
    """Encode JSON with a stable byte representation."""
    normalized = normalize_json_unicode(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return a prefixed SHA-256 digest."""
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def digest_json(value: Any) -> str:
    """Hash canonical JSON."""
    return sha256_bytes(canonical_bytes(value))
