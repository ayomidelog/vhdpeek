"""
Shared contract between the container/partition layer and the filesystem
readers.

A filesystem reader never talks to HTTP or to a VHD BAT.  It is handed a
`ByteView` -- a byte-addressable window over one partition -- and exposes a
uniform, path-based API.  That keeps every FS parser testable against a plain
`bytes` object and makes nesting (an ISO inside ext4) a one-liner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Tuple, runtime_checkable


@dataclass
class Entry:
    """One directory entry, as reported by any filesystem reader."""

    name: str
    path: str                      # absolute within the filesystem, "" = root
    is_dir: bool
    size: int = 0
    mtime: Optional[int] = None    # unix seconds, when the FS records it
    extra: Dict[str, object] = field(default_factory=dict)

    def __repr__(self) -> str:
        kind = "dir" if self.is_dir else "file"
        return f"Entry({self.path!r}, {kind}, {self.size})"


@runtime_checkable
class ByteView(Protocol):
    """
    A byte-addressable window.  `read` returns exactly `size` bytes, zero
    filled past the end of the view, and never raises for a short tail.
    """

    size: int
    sector_size: int

    def read(self, offset: int, size: int) -> bytes: ...


class BytesView:
    """`ByteView` over an in-memory blob.  Used by tests and generators."""

    def __init__(self, data: bytes, sector_size: int = 512):
        self._data = bytes(data)
        self.size = len(self._data)
        self.sector_size = sector_size

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0:
            raise ValueError("negative offset")
        if size <= 0 or offset >= self.size:
            return b"\x00" * max(0, size)
        chunk = self._data[offset:offset + size]
        if len(chunk) < size:
            chunk += b"\x00" * (size - len(chunk))
        return chunk


class ReaderView:
    """
    `ByteView` over a `(offset, size) -> bytes` callable.

    This is what makes nesting work: an ISO inside an ext4 file is just a
    `ReaderView` over that file's reader, so `IsoReader` never learns that it
    is looking at a nested image.
    """

    def __init__(self, reader, size: int, sector_size: int = 2048):
        self._reader = reader
        self.size = size
        self.sector_size = sector_size

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError(f"negative read: offset={offset} size={size}")
        if size == 0 or offset >= self.size:
            return b"\x00" * size
        data = self._reader(offset, size)
        if len(data) < size:
            data += b"\x00" * (size - len(data))
        return data


@runtime_checkable
class FsReader(Protocol):
    """Uniform filesystem API.  Paths are absolute, '/'-separated, "" = root."""

    fs_type: str

    def list_dir(self, path: str = "") -> list[Entry]: ...

    def stat(self, path: str) -> Optional[Entry]: ...

    def read_file(self, path: str, offset: int = 0,
                  size: Optional[int] = None) -> bytes: ...

    def file_reader(self, path: str) -> "ReaderFn": ...


ReaderFn = "callable(offset: int, size: int) -> bytes"


def format_size(count: float) -> str:
    """Human-readable byte count with binary units."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if count < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(count)} B"
            return f"{count:,.1f} {unit}"
        count /= 1024
    return f"{count:,.1f} TiB"


def norm_path(path: str) -> Tuple[str, ...]:
    """Normalise a filesystem path into components.  Root -> ()."""
    if not path:
        return ()
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    return tuple(parts)


def join_path(prefix: str, name: str) -> str:
    if not prefix:
        return "/" + name
    return prefix.rstrip("/") + "/" + name
