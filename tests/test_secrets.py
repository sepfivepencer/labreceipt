from __future__ import annotations

import pytest

from labreceipt.secrets import metadata_secret_kinds, secret_kinds


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("AKIA" + "ABCDEFGHIJKLMNOP", "aws_access_key"),
        ("ASIA" + "ABCDEFGHIJKLMNOP", "aws_access_key"),
        ("ghp_" + "a" * 36, "github_token"),
        ("gho_" + "B" * 40, "github_token"),
        ("sk-" + "c" * 24, "openai_key"),
        ("-----BEGIN " + "PRIVATE KEY-----", "private_key"),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", "private_key"),
    ],
)
def test_recognizes_high_confidence_secrets(text: str, expected: str) -> None:
    assert expected in secret_kinds(text)


@pytest.mark.parametrize("text", ["", "hello", "sk-short", "AKIA_TOO_SHORT", "github_token"])
def test_ordinary_text_is_not_a_secret(text: str) -> None:
    assert secret_kinds(text) == ()


def test_metadata_scans_keys_and_values() -> None:
    value = {"nested": [{"ghp_" + "x" * 36: "safe"}]}
    assert metadata_secret_kinds(value) == ("github_token",)


def test_metadata_deduplicates_detector_labels() -> None:
    value = ["sk-" + "x" * 24, "sk-" + "y" * 24]
    assert metadata_secret_kinds(value) == ("openai_key",)
