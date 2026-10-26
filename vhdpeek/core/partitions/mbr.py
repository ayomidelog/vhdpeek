"""
MBR (MS-DOS) partition tables, including the extended/logical EBR chain.

Layout: four 16-byte entries at offset 446 of LBA 0, then the 0x55AA boot
signature. An extended entry (0x05, 0x0F, 0x85) points at a chain of EBRs,
each holding one logical partition plus a relative link to the next.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Tuple

from .types import (GPT_PROTECTIVE_TYPE, MBR_EXTENDED_TYPES, MBR_TYPE_NAMES,
                    Partition)

ENTRY_TABLE_OFFSET = 446
ENTRY_SIZE = 16
SIGNATURE = b"\x55\xAA"
MAX_LOGICAL = 64


def has_boot_signature(sector: bytes) -> bool:
    return len(sector) >= 512 and sector[510:512] == SIGNATURE


def entries(sector: bytes) -> List[Tuple[int, int, int]]:
    """[(type, start_lba, sector_count), ...] for the four primary slots."""
    found = []
    for slot in range(4):
        off = ENTRY_TABLE_OFFSET + slot * ENTRY_SIZE
        found.append((
            sector[off + 4],
            struct.unpack_from("<I", sector, off + 8)[0],
            struct.unpack_from("<I", sector, off + 12)[0],
        ))
    return found


def _read(disk, lba: int, sector_size: int) -> bytes:
    return disk.read_lba(lba, 1, sector_size)


def _partition(index: int, start: int, count: int, ptype: int,
               sector_size: int) -> Partition:
    return Partition(
        index=index,
        start_lba=start,
        end_lba=start + count - 1,
        type=f"0x{ptype:02X}",
        name=MBR_TYPE_NAMES.get(ptype, f"0x{ptype:02X}"),
        sector_size=sector_size,
        scheme="mbr",
    )


def parse(disk, sector_size: Optional[int] = None) -> List[Partition]:
    """Parse LBA 0 plus any extended-partition chain."""
    sector_size = sector_size or disk.logical_sector_size
    sector = _read(disk, 0, sector_size)
    if not has_boot_signature(sector):
        return []

    partitions: List[Partition] = []
    extended_bases: List[int] = []

    for index, (ptype, start, count) in enumerate(entries(sector)):
        if ptype == 0 or count == 0 or ptype == GPT_PROTECTIVE_TYPE:
            continue
        if ptype in MBR_EXTENDED_TYPES:
            extended_bases.append(start)
            continue
        partitions.append(_partition(index, start, count, ptype, sector_size))

    next_index = 4
    for base in extended_bases:
        next_index = _parse_chain(disk, base, sector_size, partitions,
                                  next_index)
    return partitions


def _parse_chain(disk, base: int, sector_size: int,
                 out: List[Partition], next_index: int) -> int:
    ebr_lba = base
    seen = set()
    while ebr_lba not in seen and len(seen) < MAX_LOGICAL:
        seen.add(ebr_lba)
        ebr = _read(disk, ebr_lba, sector_size)
        if not has_boot_signature(ebr):
            break

        slots = entries(ebr)
        ptype, rel_start, count = slots[0]
        if ptype != 0 and count != 0:
            start = ebr_lba + rel_start
            out.append(_partition(next_index, start, count, ptype, sector_size))
            next_index += 1

        link_type, link_start, _ = slots[1]
        if link_type not in MBR_EXTENDED_TYPES or link_start == 0:
            break
        ebr_lba = base + link_start
    return next_index
