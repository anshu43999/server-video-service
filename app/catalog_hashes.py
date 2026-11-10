"""Short-lived digest reuse for one synchronous catalog-list inspection."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class CatalogFileChanged(Exception):
    """A file changed while a list projection was being assembled."""


def _change_time(handle, info):
    if os.name != 'nt':
        return info.st_ctime_ns
    # Windows st_ctime is creation time, NOT metadata change time. Query the
    # read-only FileBasicInfo handle API; unavailable metadata disables reuse.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileBasicInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in
                    ('creation', 'access', 'write', 'change')] + [('attributes', wintypes.DWORD)]

    query = ctypes.WinDLL('kernel32', use_last_error=True).GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    data = FileBasicInfo()
    if not query(msvcrt.get_osfhandle(handle.fileno()), 0, ctypes.byref(data), ctypes.sizeof(data)):
        return None
    return data.change or None


def _snapshot(path: Path):
    with path.open('rb') as handle:
        info = os.fstat(handle.fileno())
        change = _change_time(handle, info)
        # Identity + size + modification AND metadata-change times are only
        # invalidation guards. A new request always computes a full SHA-256.
        fingerprint = (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                       info.st_mtime_ns, info.st_ctime_ns, change)
        return fingerprint, bool(info.st_ino and change is not None)


@dataclass(frozen=True)
class _Digest:
    fingerprint: tuple
    value: str
    reusable: bool


class CatalogFileHashes:
    def __init__(self, compute: Callable[[Path], str]):
        self._compute = compute
        self._files: dict[Path, _Digest] = {}
        self.hash_attempts = 0
        self.hash_completed = 0
        self.hash_reuses = 0
        self.hash_seconds = 0.0

    def _hash(self, path):
        self.hash_attempts += 1
        started = time.monotonic()
        try:
            value = self._compute(path)
            self.hash_completed += 1
            return value
        finally:
            self.hash_seconds += time.monotonic() - started

    def digest(self, path: Path) -> str:
        # Do not resolve symlinks here: re-opening the original path also
        # detects a changed target. Different hard-link names are not merged.
        path = path.absolute()
        try:
            before, reusable = _snapshot(path)
            previous = self._files.get(path)
            if previous is not None:
                if before != previous.fingerprint:
                    raise CatalogFileChanged()
                if reusable and previous.reusable:
                    self.hash_reuses += 1
                    return previous.value
            value = self._hash(path)
            after, reusable_after = _snapshot(path)
            if before != after or (previous is not None and value != previous.value):
                raise CatalogFileChanged()
            self._files[path] = _Digest(after, value, reusable and reusable_after)
            return value
        except OSError as exc:
            raise CatalogFileChanged() from exc

    def verify(self):
        try:
            for path, previous in self._files.items():
                current, reusable = _snapshot(path)
                if current != previous.fingerprint:
                    raise CatalogFileChanged()
                if not (reusable and previous.reusable):
                    # Conservative fallback: no reuse, plus a final full hash.
                    # Unsupported file identity/change-time is never a hit.
                    if self._hash(path) != previous.value or _snapshot(path)[0] != current:
                        raise CatalogFileChanged()
        except OSError as exc:
            raise CatalogFileChanged() from exc

    def clear(self):
        self._files.clear()
