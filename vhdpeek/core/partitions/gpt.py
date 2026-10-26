"""
GPT (UEFI) partition tables.

Layout: a header at LBA 1 with the magic "EFI PART", pointing at an entry
array elsewhere on the disk. Each entry is 128 bytes: a type GUID, a unique
GUID, first and last LBA, attributes, and a UTF-16LE name.
"""

from __future__ import annotations

import struct
from typing import List, Optional

from .types import GPT_TYPE_GUIDS, Partition, decode_utf16le, guid_string

MAGIC = b"EFI PART"
MIN_ENTRY_SIZE = 128
MAX_ENTRY_SIZE = 4096
MAX_ENTRIES = 4096
MIN_HEADER_SIZE = 92


def parse(disk, sector_size: Optional[int] = None) -> List[Partition]:
    """Parse the primary GPT header at LBA 1 and its entry array."""
    sector_size = sector_size or disk.logical_sector_size
    header = disk.read_lba(1, 1, sector_size)
    if header[:8] != MAGIC:
        return []

    header_size = struct.unpack_from("<I", header, 12)[0]
    if not MIN_HEADER_SIZE <= header_size <= sector_size:
        return []

    entries_lba = struct.unpack_from("<Q", header, 72)[0]
    entry_count = struct.unpack_from("<I", header, 80)[0]
    entry_size = struct.unpack_from("<I", header, 84)[0]
    if not MIN_ENTRY_SIZE <= entry_size <= MAX_ENTRY_SIZE:
        return []
    if not 0 < entry_count <= MAX_ENTRIES:
        return []

    total = entry_count * entry_size
    raw = disk.read(entries_lba * sector_size, total)

    partitions: List[Partition] = []
    for index in range(entry_count):
        entry = raw[index * entry_size:(index + 1) * entry_size]
        if len(entry) < entry_size or entry[:16] == b"\x00" * 16:
            continue

        first = struct.unpack_from("<Q", entry, 32)[0]
        last = struct.unpack_from("<Q", entry, 40)[0]
        if last == 0 or last < first:
            continue

        type_guid = guid_string(entry[:16])
        name = decode_utf16le(entry[56:128]) if entry_size >= 128 else None
        partitions.append(Partition(
            index=len(partitions),
            start_lba=first,
            end_lba=last,
            type=GPT_TYPE_GUIDS.get(type_guid, type_guid[:8]),
            type_guid=type_guid,
            name=name,
            sector_size=sector_size,
            scheme="gpt",
        ))
    return partitions
