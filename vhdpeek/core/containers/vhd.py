"""
Legacy VHD containers: fixed, dynamic and differencing.

On-disk references (MS-VHD 1.0):

  footer    512 B at the end of the file, cookie "conectix";
            disk type at 60 (2 fixed, 3 dynamic, 4 differencing),
            current size at 48, data offset at 16.
  header    1024 B at footer.data_offset, cookie "cxsparse";
            BAT offset at 16, max entries at 28, block size at 32.
            Each block is a 512-byte sector bitmap followed by the data.
"""

from __future__ import annotations

import struct
from typing import Optional

from ..source import Source
from .info import VHDInfo

COOKIE = b"conectix"
DYNAMIC_COOKIE = b"cxsparse"

DISK_TYPE_FIXED = 2
DISK_TYPE_DYNAMIC = 3
DISK_TYPE_DIFFERENCING = 4

SECTOR = 512
DEFAULT_BLOCK_SIZE = 2 << 20


def _u32be(buf: bytes, off: int) -> int:
    return struct.unpack_from(">I", buf, off)[0]


def _u64be(buf: bytes, off: int) -> int:
    return struct.unpack_from(">Q", buf, off)[0]


def parse(source: Source, file_size: int) -> VHDInfo:
    """Parse a legacy VHD whose footer sits at the end of `source`."""
    footer = source.read(file_size - 512, 512)
    if footer[:8] != COOKIE:
        raise ValueError("not a VHD: footer cookie missing")

    disk_type = _u32be(footer, 60)
    current_size = _u64be(footer, 48)
    data_offset = _u64be(footer, 16)

    if disk_type == DISK_TYPE_FIXED:
        return VHDInfo(
            source=source,
            file_size=file_size,
            virtual_size=current_size,
            disk_type="fixed",
            block_size=SECTOR,
            data_start=0,
        )

    if disk_type not in (DISK_TYPE_DYNAMIC, DISK_TYPE_DIFFERENCING):
        raise ValueError(f"unsupported VHD disk type {disk_type}")

    return _parse_dynamic(source, file_size, disk_type, current_size,
                          data_offset)


def _parse_dynamic(source: Source, file_size: int, disk_type: int,
                   current_size: int, data_offset: int) -> VHDInfo:
    header = source.read(data_offset, 1024)
    if header[:8] != DYNAMIC_COOKIE:
        raise ValueError("not a dynamic VHD: 'cxsparse' header missing")

    bat_offset = _u64be(header, 16)
    max_entries = _u32be(header, 28)
    block_size = _u32be(header, 32) or DEFAULT_BLOCK_SIZE

    parent_name: Optional[str] = None
    if disk_type == DISK_TYPE_DIFFERENCING:
        raw = header[64:576].decode("utf-16-be", "replace").rstrip("\x00")
        parent_name = raw or None

    return VHDInfo(
        source=source,
        file_size=file_size,
        virtual_size=current_size,
        disk_type=("differencing" if disk_type == DISK_TYPE_DIFFERENCING
                   else "dynamic"),
        block_size=block_size,
        has_parent=disk_type == DISK_TYPE_DIFFERENCING,
        parent_name=parent_name,
        bat_offset=bat_offset,
        bat_entries=max_entries,
        bat_entry_size=4,
        sector_bitmap_size=bitmap_size(block_size),
    )


def bitmap_size(block_size: int) -> int:
    """One bit per sector in the block, padded up to a whole sector."""
    sectors = block_size // SECTOR
    bitmap = (sectors + 7) // 8
    return (bitmap + SECTOR - 1) // SECTOR * SECTOR
