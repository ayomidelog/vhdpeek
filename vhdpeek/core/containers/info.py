"""
A parsed virtual disk.

`VHDInfo` owns the virtual-to-file mapping: for any virtual byte offset it
produces the backing file offset, or says "this is an unallocated hole".
Nothing above this layer knows which container format it is looking at.

The BAT is read a page at a time. A 60 GiB dynamic disk has a BAT of a few
hundred kilobytes, and a VHDX can have more; loading it whole would defeat
the point of browsing an image remotely.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from ..source import Source
from ..volume import format_size

BAT_PAGE = 4096

# VHDX BAT payload block states.
BLOCK_NOT_PRESENT = 0
BLOCK_UNDEFINED = 1
BLOCK_ZERO = 2
BLOCK_UNMAPPED = 3
BLOCK_FULLY_PRESENT = 4
BLOCK_PARTIALLY_PRESENT = 5
BLOCK_HAS_DATA = (BLOCK_FULLY_PRESENT, BLOCK_PARTIALLY_PRESENT)

HOLE = 0xFFFFFFFF


@dataclass
class VHDInfo:
    """
    A parsed virtual disk.

    `read` is the only entry point callers need; it zero-fills holes and
    clamps to the virtual size, so the layers above never see a short read.
    """

    source: Source
    file_size: int
    virtual_size: int
    disk_type: str                      # fixed | dynamic | differencing | vhdx
    logical_sector_size: int = 512
    physical_sector_size: int = 512
    block_size: int = 512               # container block, not sector
    has_parent: bool = False
    parent_name: Optional[str] = None
    is_dirty: bool = False              # VHDX log needs replay

    # BAT access
    bat_offset: int = 0
    bat_entries: int = 0
    bat_entry_size: int = 4
    bat_little_endian: bool = False
    sector_bitmap_size: int = 0         # VHD dynamic/differencing
    chunk_ratio: int = 0                # VHDX differencing: payload per bitmap
    data_start: int = 0                 # fixed VHD: 0; VHDX: unused

    _bat_pages: Dict[int, bytes] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # BAT access
    # ------------------------------------------------------------------

    def _bat_page(self, page: int) -> bytes:
        cached = self._bat_pages.get(page)
        if cached is None:
            start = self.bat_offset + page * BAT_PAGE
            want = min(BAT_PAGE, self.bat_entries * self.bat_entry_size
                       - page * BAT_PAGE)
            cached = self.source.read(start, want)
            self._bat_pages[page] = cached
            if len(self._bat_pages) > 256:
                self._bat_pages.pop(next(iter(self._bat_pages)))
        return cached

    def _bat_value(self, index: int) -> int:
        """Raw BAT entry, or a hole marker when past the table."""
        if index < 0 or index >= self.bat_entries:
            return HOLE
        byte_off = index * self.bat_entry_size
        page, page_off = divmod(byte_off, BAT_PAGE)
        buf = self._bat_page(page)
        if page_off + self.bat_entry_size > len(buf):
            return HOLE
        fmt = "<" if self.bat_little_endian else ">"
        if self.bat_entry_size == 8:
            return struct.unpack_from(f"{fmt}Q", buf, page_off)[0]
        return struct.unpack_from(f"{fmt}I", buf, page_off)[0]

    # ------------------------------------------------------------------
    # Virtual -> file mapping
    # ------------------------------------------------------------------

    def _map_block(self, block: int, within: int, limit: int
                   ) -> Tuple[int, Optional[int]]:
        """(bytes available in this run, file offset or None for a hole)."""
        if self.disk_type == "fixed":
            run = min(limit, self.block_size - within)
            return run, self.data_start + block * self.block_size + within

        if self.disk_type in ("dynamic", "differencing"):
            entry = self._bat_value(block)
            run = min(limit, self.block_size - within)
            if entry == HOLE:
                return run, None
            # Block data starts after the block's sector bitmap.
            return run, entry * 512 + self.sector_bitmap_size + within

        # VHDX: one BAT entry per payload block, plus one sector-bitmap entry
        # per chunk when the image is differencing.
        index = block + (block // self.chunk_ratio if self.chunk_ratio else 0)
        entry = self._bat_value(index)
        run = min(limit, self.block_size - within)
        if entry == HOLE:
            return run, None
        if (entry & 0x7) not in BLOCK_HAS_DATA:
            return run, None
        return run, ((entry >> 20) << 20) + within

    def _map_run(self, offset: int, limit: int) -> Tuple[int, Optional[int]]:
        """
        Map the run starting at `offset`, coalescing consecutive container
        blocks that are contiguous both virtually and in the file. One run
        becomes one `Source.read`, which keeps HTTP request counts low.
        """
        block, within = divmod(offset, self.block_size)
        run, file_offset = self._map_block(block, within, limit)
        if file_offset is None:
            while run < limit:
                nxt_run, nxt_off = self._map_block(block + 1, 0, limit - run)
                if nxt_off is not None:
                    break
                run += nxt_run
                block += 1
            return run, None

        while run < limit:
            nxt_run, nxt_off = self._map_block(block + 1, 0, limit - run)
            if nxt_off != file_offset + run:
                break
            run += nxt_run
            block += 1
        return run, file_offset

    # ------------------------------------------------------------------
    # Public reads
    # ------------------------------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        """Read virtual bytes; holes and the tail past EOF read as zeros."""
        if offset < 0 or size < 0:
            raise ValueError(f"negative read: offset={offset} size={size}")
        if size == 0 or offset >= self.virtual_size:
            return b""
        size = min(size, self.virtual_size - offset)

        out = bytearray(size)
        done = 0
        while done < size:
            run, file_offset = self._map_run(offset + done, size - done)
            if file_offset is not None:
                out[done:done + run] = self.source.read(file_offset, run)
            done += run
        return bytes(out)

    def read_lba(self, lba: int, count: int = 1,
                 sector_size: Optional[int] = None) -> bytes:
        sector = sector_size or self.logical_sector_size
        return self.read(lba * sector, count * sector)

    @property
    def sector_size(self) -> int:
        """Alias for the logical sector size."""
        return self.logical_sector_size

    def describe(self) -> str:
        return (f"{self.disk_type.upper()}  "
                f"virtual {format_size(self.virtual_size)}  "
                f"file {format_size(self.file_size)}  "
                f"sector {self.logical_sector_size}  "
                f"block {self.block_size}")
