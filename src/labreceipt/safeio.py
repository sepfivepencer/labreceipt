"""Race-resistant reads and exclusive writes."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path, PurePosixPath

from labreceipt.errors import LabReceiptError

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _require_nofollow() -> None:
    if _NOFOLLOW == 0:
        raise LabReceiptError("platform lacks required no-follow file semantics")


def validate_relative_path(value: str) -> tuple[str, ...]:
    """Validate a portable workspace-relative file path."""
    if not value or "\x00" in value or "\\" in value:
        raise LabReceiptError("artifact path must be a non-empty portable relative path")
    raw_parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in raw_parts):
        raise LabReceiptError("artifact path must stay inside the workspace")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise LabReceiptError("artifact path must stay inside the workspace")
    if len(value.encode("utf-8")) > 512 or len(path.parts) > 32:
        raise LabReceiptError("artifact path exceeds the safety limit")
    return path.parts


def _open_directory(path: Path) -> int:
    _require_nofollow()
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        descriptor = os.open(os.sep, os.O_RDONLY | _DIRECTORY)
    except OSError as exc:
        raise LabReceiptError("directory root cannot be opened safely") from exc
    try:
        for part in absolute.parts[1:]:
            try:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=descriptor,
                )
            except OSError as exc:
                raise LabReceiptError("directory path contains a symlink or non-directory") from exc
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def read_workspace_file(root: Path, relative: str, limit: int) -> tuple[bytes, int]:
    """Read a regular file under root while refusing symlink components."""
    parts = validate_relative_path(relative)
    descriptor = _open_directory(root)
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | _NOFOLLOW
            if index < len(parts) - 1:
                flags |= _DIRECTORY
            try:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError as exc:
                raise LabReceiptError("artifact is missing") from exc
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise LabReceiptError(
                        "artifact path contains a symlink or non-directory"
                    ) from exc
                raise LabReceiptError("artifact cannot be opened safely") from exc
            os.close(descriptor)
            descriptor = next_descriptor
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise LabReceiptError("artifact is not a regular file")
        if info.st_size > limit:
            raise LabReceiptError("artifact exceeds its byte limit")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > limit:
            raise LabReceiptError("artifact exceeds its byte limit")
        return data, len(data)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def read_user_file(path: Path, limit: int) -> bytes:
    """Read an explicitly selected file and reject every symlink component."""
    parent_descriptor = _open_directory(path.parent)
    try:
        try:
            descriptor = os.open(path.name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_descriptor)
        except OSError as exc:
            raise LabReceiptError("input file cannot be opened safely") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise LabReceiptError("input file is not a regular file within the size limit")
            chunks: list[bytes] = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > limit:
                raise LabReceiptError("input file exceeds the size limit")
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_descriptor)


def exclusive_write(path: Path, data: bytes) -> None:
    """Create a new regular file without following the final path as a symlink."""
    try:
        parent_descriptor = _open_directory(path.parent)
    except LabReceiptError as exc:
        raise LabReceiptError("output parent must be an existing non-symlink directory") from exc
    try:
        try:
            descriptor = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                0o600,
                dir_fd=parent_descriptor,
            )
        except FileExistsError as exc:
            raise LabReceiptError("output already exists; overwrite is disabled") from exc
        except OSError as exc:
            raise LabReceiptError("output cannot be created safely") from exc
        try:
            offset = 0
            while offset < len(data):
                written = os.write(descriptor, data[offset:])
                if written <= 0:
                    raise LabReceiptError("output write did not make progress")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_descriptor)


def preflight_output(path: Path) -> None:
    """Fail before expensive work when an output cannot be created safely."""
    try:
        parent_descriptor = _open_directory(path.parent)
    except LabReceiptError as exc:
        raise LabReceiptError("output parent must be an existing non-symlink directory") from exc
    try:
        try:
            os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise LabReceiptError("output target cannot be inspected safely") from exc
        raise LabReceiptError("output already exists; overwrite is disabled")
    finally:
        os.close(parent_descriptor)
