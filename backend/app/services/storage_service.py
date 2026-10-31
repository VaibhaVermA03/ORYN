"""File storage abstraction.

`LocalStorage` writes under STORAGE_DIR. On Render this directory MUST be a persistent disk
mount (container filesystems are ephemeral). To use object storage (S3, R2, GCS) implement the
`Storage` protocol and return it from `get_storage()`; nothing else in the app touches paths.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings
from app.core.exceptions import PayloadTooLarge

_CHUNK = 1024 * 1024


class Storage(Protocol):
    def save(self, key: str, source: BinaryIO, max_bytes: int) -> tuple[int, str]: ...

    @contextmanager
    def open_local(self, key: str) -> Iterator[Path]: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...


def sanitize_filename(name: str) -> str:
    """Return a safe display name: no path components, control characters or odd whitespace."""
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "document"
    stem, dot, ext = name.rpartition(".")
    if len(name) > 200:
        keep = 200 - (len(ext) + 1 if dot else 0)
        name = (stem[:keep] + "." + ext) if dot else name[:200]
    return name


class LocalStorage:
    def __init__(self, root: str, temp_dir: str) -> None:
        self.root = Path(root).resolve()
        self.temp = Path(temp_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:  # defence in depth against path traversal
            raise ValueError("Invalid storage key")
        return p

    def save(self, key: str, source: BinaryIO, max_bytes: int) -> tuple[int, str]:
        """Stream `source` to storage, enforcing `max_bytes`. Returns (size, sha256 hex)."""
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, tmp_name = tempfile.mkstemp(dir=self.temp, prefix="upload-")
        try:
            with os.fdopen(fd, "wb") as out:
                while True:
                    block = source.read(_CHUNK)
                    if not block:
                        break
                    size += len(block)
                    if size > max_bytes:
                        raise PayloadTooLarge(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
                    digest.update(block)
                    out.write(block)
            shutil.move(tmp_name, dest)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return size, digest.hexdigest()

    @contextmanager
    def open_local(self, key: str) -> Iterator[Path]:
        yield self._path(key)

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except ValueError:
            return

    def delete_prefix(self, prefix: str) -> None:
        shutil.rmtree(self._path(prefix), ignore_errors=True)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = LocalStorage(s.storage_dir, s.temp_dir)
    return _storage


def set_storage(storage: Storage | None) -> None:
    global _storage
    _storage = storage
