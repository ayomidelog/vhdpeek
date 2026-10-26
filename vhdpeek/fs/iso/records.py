"""Data records and low-level ISO 9660 decoding helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

_MULTI_EXTENT = 0x80
_IS_DIRECTORY = 0x02


@dataclass(frozen=True)
class _Extent:
    """One contiguous file section, already resolved to a byte offset."""

    offset: int
    size: int


@dataclass
class _Record:
    """A directory record with names resolved and multi-extents merged."""

    name: str
    identifier: bytes
    is_dir: bool
    extents: List[_Extent]
    mtime: Optional[int]
    flags: int
    relocated: bool = False

    @property
    def size(self) -> int:
        return sum(extent.size for extent in self.extents)


@dataclass
class _RrInfo:
    """The subset of Rock Ridge fields this reader consumes."""

    name: Optional[str] = None
    child_lba: Optional[int] = None
    relocated: bool = False
    name_bytes: bytes = field(default=b"", repr=False)


def _strip_version(name: str) -> str:
    """Drop an ISO 9660 ``;version`` suffix from a file identifier."""
    semi = name.rfind(";")
    if semi < 0:
        return name
    suffix = name[semi + 1:]
    if suffix == "" or suffix.isdigit():
        return name[:semi]
    return name


def _decode_rr_name(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _parse_time(raw: bytes) -> Optional[int]:
    """Convert an ISO 9660 7-byte recording date to Unix seconds."""
    if len(raw) < 7:
        return None
    year = raw[0] + 1900
    month, day, hour, minute, second = raw[1:6]
    offset = raw[6]
    if offset > 127:
        offset -= 256
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        stamp = datetime(year, month, day, hour, minute, second,
                         tzinfo=timezone(timedelta(minutes=offset * 15)))
        return int(stamp.timestamp())
    except (ValueError, OSError, OverflowError):
        return None
