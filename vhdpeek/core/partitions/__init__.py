"""Partition tables: MBR with its extended chain, and GPT."""

from .types import Partition
from .view import PartitionView

__all__ = ["Partition", "PartitionView", "parse_partitions"]


def parse_partitions(disk) -> list:
    """
    Detect and parse the partition table.

    A protective-MBR entry (0xEE) or an "EFI PART" header at LBA 1 selects
    GPT; otherwise MBR, including logical partitions inside an extended
    partition.
    """
    from . import gpt, mbr

    sector_size = disk.logical_sector_size
    sector = disk.read_lba(0, 1, sector_size)

    if sector[:8] == b"EFI PART":
        return gpt.parse(disk, sector_size)

    if not mbr.has_boot_signature(sector):
        return []

    protective = any(ptype == 0xEE for ptype, _, _ in mbr.entries(sector))
    if protective:
        found = gpt.parse(disk, sector_size)
        if found:
            return found

    found = mbr.parse(disk, sector_size)
    if found:
        return found

    return gpt.parse(disk, sector_size)
