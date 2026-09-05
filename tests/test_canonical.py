from __future__ import annotations

import pytest

from labreceipt.canonical import canonical_bytes, digest_json, sha256_bytes
from labreceipt.errors import LabReceiptError


def test_canonical_sorts_keys() -> None:
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_preserves_unicode() -> None:
    assert canonical_bytes({"text": "验收"}).decode() == '{"text":"验收"}'


def test_canonical_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_bytes(float("nan"))


def test_sha256_is_prefixed() -> None:
    assert sha256_bytes(b"").startswith("sha256:")
    assert len(sha256_bytes(b"")) == 71


def test_digest_json_ignores_dict_insertion_order() -> None:
    assert digest_json({"a": 1, "b": 2}) == digest_json({"b": 2, "a": 1})


def test_digest_json_changes_with_array_order() -> None:
    assert digest_json([1, 2]) != digest_json([2, 1])


@pytest.mark.parametrize("value", ["\ud800", "\udfff", "ok\ud800", {"\udc00": 1}])
def test_canonical_rejects_unpaired_surrogate(value: object) -> None:
    with pytest.raises(LabReceiptError, match="unpaired"):
        canonical_bytes(value)


def test_canonical_combines_valid_surrogate_pair() -> None:
    assert canonical_bytes("\ud83d\ude00") == canonical_bytes("😀")


def test_canonical_rejects_key_collision_after_pair_normalization() -> None:
    with pytest.raises(LabReceiptError, match="duplicate"):
        canonical_bytes({"\ud83d\ude00": 1, "😀": 2})
