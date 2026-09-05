"""High-confidence secret recognition without returning secret text."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

_PATTERNS = (
    ("aws_access_key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("github_token", re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,255}")),
    ("openai_key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)


def secret_kinds(text: str) -> tuple[str, ...]:
    """Return only detector labels, never matching spans."""
    return tuple(name for name, pattern in _PATTERNS if pattern.search(text))


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)


def metadata_secret_kinds(value: Any) -> tuple[str, ...]:
    """Scan all JSON strings and return unique detector labels."""
    kinds: set[str] = set()
    for text in _strings(value):
        kinds.update(secret_kinds(text))
    return tuple(sorted(kinds))
