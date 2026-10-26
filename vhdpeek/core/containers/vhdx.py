"""
VHDX containers.

On-disk references (MS-VHDX):

  file id      "vhdxfile" at 0.
  headers      "head" at 64 KiB and 128 KiB; a non-zero log GUID at offset
               48 means the image was not cleanly closed.
  region table "regi" at 192 KiB and 256 KiB, listing the BAT and metadata
               regions by GUID.
  metadata     "metadata" table, whose items carry the virtual size, sector
               sizes and block size.
  BAT entry    state in bits 0..2, file offset in MiB in bits 20..63.
"""

from __future__ import annotations

import struct
from typing import Dict, Optional, Tuple

from ..source import Source
from .info import VHDInfo

COOKIE = b"vhdxfile"

# Region and metadata identifiers, in canonical GUID form.
GUID_BAT = "2DC27766-F623-4200-9D64-115E9BFD4A08"
GUID_METADATA = "8B7CA206-4790-4B9A-B8FE-575F050F886E"
GUID_FILE_PARAMETERS = "CAA16737-FA36-4D43-B3B6-33F0AA44E76B"
GUID_VIRTUAL_SIZE = "2FA54224-CD1B-4876-B211-5DBED83BF4B8"
GUID_LOGICAL_SECTOR = "8141BF1D-A96F-4709-BA47-F233A8FAAB5F"
GUID_PHYSICAL_SECTOR = "CDA348C7-445D-4471-9CC9-E9885251C556"
GUID_PARENT_LOCATOR = "A8D35F2D-B30B-454D-ABF7-D3D84834AB0C"

REGION_TABLE_OFFSETS = (192 << 10, 256 << 10)
HEADER_OFFSET = 64 << 10
DEFAULT_BLOCK_SIZE = 1 << 20


def _u16le(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def _u32le(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _u64le(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


def guid_string(raw: bytes) -> str:
    """Canonical string form of a 16-byte on-disk GUID."""
    d1, d2, d3 = struct.unpack_from("<IHH", raw, 0)
    return (f"{d1:08X}-{d2:04X}-{d3:04X}-"
            f"{raw[8]:02X}{raw[9]:02X}-{raw[10:16].hex().upper()}")


def read_region_table(source: Source, offset: int
                      ) -> Optional[Dict[str, Tuple[int, int]]]:
    try:
        head = source.read(offset, 64)
    except EOFError:
        return None
    if head[:4] != b"regi":
        return None
    count = _u32le(head, 8)
    if count == 0 or count > 2048:
        return None
    raw = source.read(offset + 16, count * 32)
    regions: Dict[str, Tuple[int, int]] = {}
    for i in range(count):
        entry = raw[i * 32:(i + 1) * 32]
        regions[guid_string(entry[:16])] = (_u64le(entry, 16), _u32le(entry, 24))
    return regions


def read_metadata(source: Source, offset: int, length: int) -> Dict[str, bytes]:
    """
    Read the metadata table and just the items it points at.

    The region is at least 1 MiB, but the table and the handful of items we
    need are a few hundred bytes; reading the whole region would download a
    megabyte to learn the virtual disk size.
    """
    head = source.read(offset, 32)
    if head[:8] != b"metadata":
        raise ValueError("VHDX metadata region header missing")
    count = _u16le(head, 10)
    if count == 0 or count > 2048:
        raise ValueError(f"VHDX metadata table has {count} entries")

    table = source.read(offset + 32, count * 32)
    items: Dict[str, bytes] = {}
    for i in range(count):
        entry = table[i * 32:(i + 1) * 32]
        if len(entry) < 32:
            break
        item_off = _u32le(entry, 16)
        item_len = _u32le(entry, 20)
        if item_len == 0 or item_len > (1 << 20):
            continue
        if item_off + item_len > max(length, 1 << 16):
            continue
        items[guid_string(entry[:16])] = source.read(offset + item_off, item_len)
    return items


def parse(source: Source, file_size: int) -> VHDInfo:
    """Parse a VHDX whose file identifier is at offset 0."""
    if source.read(0, 8).lower() != COOKIE:
        raise ValueError("not a VHDX file: identifier missing")

    regions = None
    for table_off in REGION_TABLE_OFFSETS:
        regions = read_region_table(source, table_off)
        if regions and GUID_BAT in regions and GUID_METADATA in regions:
            break
        regions = None
    if not regions:
        raise ValueError("VHDX region table missing BAT or metadata region")

    bat_offset, bat_length = regions[GUID_BAT]
    meta_offset, meta_length = regions[GUID_METADATA]
    items = read_metadata(source, meta_offset, meta_length)

    def need(guid: str, what: str) -> bytes:
        try:
            return items[guid]
        except KeyError:
            raise ValueError(f"VHDX metadata item missing: {what}") from None

    virtual_size = _u64le(need(GUID_VIRTUAL_SIZE, "virtual size"), 0)
    logical_sector = _u32le(need(GUID_LOGICAL_SECTOR, "logical sector size"), 0)
    physical_sector = _u32le(need(GUID_PHYSICAL_SECTOR, "physical sector size"), 0)

    file_params = need(GUID_FILE_PARAMETERS, "file parameters")
    block_size = _u32le(file_params, 0) or DEFAULT_BLOCK_SIZE
    has_parent = bool(_u32le(file_params, 4) & 0x2)

    parent_name = None
    if GUID_PARENT_LOCATOR in items:
        raw = items[GUID_PARENT_LOCATOR]
        parent_name = raw.decode("utf-16-le", "replace").rstrip("\x00") or None

    chunk_ratio = 0
    if has_parent:
        # One sector-bitmap entry per chunk of payload blocks.
        chunk_ratio = max(1, (1 << 23) * logical_sector // block_size)

    # A non-zero log GUID means the log would have to be replayed; reads may
    # be stale.
    header = source.read(HEADER_OFFSET, 4096)
    dirty = header[:4] == b"head" and header[48:64] != b"\x00" * 16

    return VHDInfo(
        source=source,
        file_size=file_size,
        virtual_size=virtual_size,
        disk_type="vhdx",
        logical_sector_size=logical_sector or 512,
        physical_sector_size=physical_sector or 512,
        block_size=block_size,
        has_parent=has_parent,
        parent_name=parent_name,
        is_dirty=dirty,
        bat_offset=bat_offset,
        bat_entries=bat_length // 8,
        bat_entry_size=8,
        bat_little_endian=True,
        chunk_ratio=chunk_ratio,
    )
