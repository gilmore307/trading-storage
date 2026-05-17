"""Atomic and locked filesystem write helpers for storage-owned artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:  # pragma: no cover - fcntl is available on the Linux deployment target.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """Atomically replace ``path`` with ``content`` after writing a temp file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=path.parent, prefix=f".{path.name}.") as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomically replace ``path`` with text content."""

    write_bytes_atomic(path, content.encode(encoding))


def append_text_locked(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Append text under an advisory lock to avoid interleaved JSONL rows."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding=encoding) as lock_handle:
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            with path.open("a", encoding=encoding) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
