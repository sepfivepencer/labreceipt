from __future__ import annotations

import os
from pathlib import Path

import pytest

from labreceipt.errors import LabReceiptError
from labreceipt.safeio import (
    exclusive_write,
    preflight_output,
    read_user_file,
    read_workspace_file,
    validate_relative_path,
)


@pytest.mark.parametrize("value", ["", "/absolute", "../escape", "a/../b", "a\\b", "./a"])
def test_rejects_unsafe_relative_paths(value: str) -> None:
    with pytest.raises(LabReceiptError):
        validate_relative_path(value)


def test_accepts_nested_portable_path() -> None:
    assert validate_relative_path("a/b.json") == ("a", "b.json")


def test_reads_regular_workspace_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"abc")
    assert read_workspace_file(tmp_path, "a.txt", 3) == (b"abc", 3)


def test_rejects_workspace_file_over_limit(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"abcd")
    with pytest.raises(LabReceiptError, match="byte limit"):
        read_workspace_file(tmp_path, "a.txt", 3)


def test_rejects_workspace_symlink_final(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("private")
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(LabReceiptError, match="symlink"):
        read_workspace_file(tmp_path, "link", 100)


def test_rejects_workspace_symlink_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a").write_text("private")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(LabReceiptError, match="symlink"):
        read_workspace_file(tmp_path, "linked/a", 100)


def test_rejects_non_regular_workspace_artifact(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()
    with pytest.raises(LabReceiptError, match="regular"):
        read_workspace_file(tmp_path, "folder", 100)


def test_read_user_file_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("private")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(LabReceiptError, match="opened safely"):
        read_user_file(link, 100)


def test_read_user_file_rejects_symlink_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "file").write_text("private")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(LabReceiptError, match="symlink"):
        read_user_file(link / "file", 100)


def test_read_user_file_collects_short_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "input"
    path.write_bytes(b"abcdef")
    original_read = os.read

    def short_read(descriptor: int, amount: int) -> bytes:
        return original_read(descriptor, min(amount, 1))

    monkeypatch.setattr(os, "read", short_read)
    assert read_user_file(path, 10) == b"abcdef"


def test_exclusive_write_creates_mode_600(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    exclusive_write(output, b"{}\n")
    assert output.read_bytes() == b"{}\n"
    assert os.stat(output).st_mode & 0o777 == 0o600


def test_exclusive_write_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    output.write_text("old")
    with pytest.raises(LabReceiptError, match="overwrite"):
        exclusive_write(output, b"new")
    assert output.read_text() == "old"


def test_exclusive_write_refuses_symlink_output(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("old")
    output = tmp_path / "receipt.json"
    output.symlink_to(target)
    with pytest.raises(LabReceiptError, match="overwrite"):
        exclusive_write(output, b"new")
    assert target.read_text() == "old"


def test_exclusive_write_refuses_symlink_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(LabReceiptError, match="non-symlink"):
        exclusive_write(linked / "new", b"new")


def test_preflight_output_accepts_new_path(tmp_path: Path) -> None:
    output = tmp_path / "new.json"
    preflight_output(output)
    assert not output.exists()


def test_preflight_output_rejects_existing_path(tmp_path: Path) -> None:
    output = tmp_path / "existing.json"
    output.write_text("old")
    with pytest.raises(LabReceiptError, match="overwrite"):
        preflight_output(output)


def test_preflight_output_rejects_symlink_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(LabReceiptError, match="non-symlink"):
        preflight_output(linked / "new.json")
