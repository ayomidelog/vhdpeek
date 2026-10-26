"""
A byte window over one partition.

`PartitionView` is the only thing the filesystem layer sees. It satisfies the
`ByteView` protocol, so a parser can be tested against a plain `bytes` object
just as easily as against a disk image.
"""

from __future__ import annotations

from ..containers import VHDInfo
from .types import Partition


class PartitionView:
    """
    Byte window over one partition.

    Reads are delegated to the virtual disk, so holes in a sparse container
    read as zeros; anything past the partition's end also reads as zeros
    rather than raising, which keeps parsers free of bounds special cases.
    """

    def __init__(self, disk: VHDInfo, partition: Partition):
        self.disk = disk
        self.partition = partition
        self.start = partition.start_offset
        self.size = partition.size_bytes
        self.sector_size = partition.sector_size

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError(f"negative read: offset={offset} size={size}")
        if size == 0:
            return b""
        if offset >= self.size:
            return b"\x00" * size
        want = min(size, self.size - offset)
        data = self.disk.read(self.start + offset, want)
        if len(data) < size:
            data += b"\x00" * (size - len(data))
        return data

    def read_lba(self, lba: int, count: int = 1) -> bytes:
        return self.read(lba * self.sector_size, count * self.sector_size)

    def __repr__(self) -> str:
        return f"PartitionView(start={self.partition.start_lba}, size={self.size})"
