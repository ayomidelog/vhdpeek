"""Shared NTFS constants, data structures and little-endian helpers."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional

ATTR_ATTRIBUTE_LIST = 0x20
ATTR_VOLUME_NAME = 0x60
ATTR_DATA = 0x80
ATTR_INDEX_ROOT = 0x90
ATTR_INDEX_ALLOCATION = 0xA0

ATTR_FLAG_COMPRESSED = 0x0001

FILE_RECORD_IN_USE = 0x0001
FILE_RECORD_IS_DIR = 0x0002

INDEX_ENTRY_HAS_SUBNODE = 0x0001
INDEX_ENTRY_LAST = 0x0002

FILE_NAME_DIRECTORY = 0x10000000
MFT_REF_MASK = 0x0000FFFFFFFFFFFF

ROOT_MFT = 5

_FILETIME_EPOCH = 116444736000000000
_MISSING = object()


@dataclass
class _Run:
    """One extent of a non-resident stream.  `lcn is None` means a hole."""

    vcn: int
    lcn: Optional[int]
    count: int


@dataclass
class _Attr:
    type: int
    name: str
    flags: int
    resident: bool
    value: bytes = b""
    runs: List[_Run] = field(default_factory=list)
    data_size: int = 0
    initialized_size: int = 0
    compression_unit: int = 0


@dataclass
class _Record:
    number: int
    sequence: int
    flags: int
    attrs: List[_Attr]
    base_ref: int


@dataclass
class _IndexEntry:
    ref: int
    name: str
    namespace: int
    is_dir: bool
    size: int
    mtime: Optional[int]

    @property
    def mft(self) -> int:
        return self.ref & MFT_REF_MASK

    @property
    def sequence(self) -> int:
        return self.ref >> 48


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _u64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


def _i8(buf: bytes, off: int) -> int:
    return struct.unpack_from("<b", buf, off)[0]


def _filetime(value: int) -> Optional[int]:
    """FILETIME (100 ns ticks since 1601) -> unix seconds."""
    if not value:
        return None
    return (value - _FILETIME_EPOCH) // 10_000_000


def _normalize_runs(runs: List[_Run]) -> List[_Run]:
    """Sort by VCN, trim overlaps and merge physically contiguous extents."""
    if not runs:
        return []
    ordered = sorted(runs, key=lambda r: r.vcn)
    out: List[_Run] = []
    for run in ordered:
        if run.count <= 0:
            continue
        if out:
            prev = out[-1]
            prev_end = prev.vcn + prev.count
            if run.vcn < prev_end:
                skip = prev_end - run.vcn
                if skip >= run.count:
                    continue
                run = _Run(
                    run.vcn + skip,
                    None if run.lcn is None else run.lcn + skip,
                    run.count - skip,
                )
            if run.vcn == prev_end:
                if run.lcn is None and prev.lcn is None:
                    prev.count += run.count
                    continue
                if (
                    run.lcn is not None
                    and prev.lcn is not None
                    and run.lcn == prev.lcn + prev.count
                ):
                    prev.count += run.count
                    continue
        out.append(run)
    return out
