"""Data runs: extent trees, indirect block maps and range reads."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Iterator, Tuple

from .constants import (
    EXT4_EXT_MAGIC,
    EXT4_EXT_MAX_DEPTH,
    EXT4_EXT_UNWRITTEN,
    INODE_EXTENTS,
    _u16,
    _u32,
)

if TYPE_CHECKING:
    from .inode import _Inode
    from .reader import Ext4Reader


def _extent_runs(reader: "Ext4Reader", node: bytes, start: int, end: int,
                 depth: int) -> Iterator[Tuple[int, int, int]]:
    """Yield (logical, physical, count) for initialized data in a node."""
    magic, entries, max_entries, node_depth, _gen = struct.unpack_from(
        "<HHHHI", node, 0)
    if magic != EXT4_EXT_MAGIC:
        raise ValueError(f"bad extent tree magic {magic:#06x}")
    if node_depth != depth or depth > EXT4_EXT_MAX_DEPTH:
        raise ValueError("corrupt extent tree depth")
    # eh_max already excludes the metadata_csum tail of the node
    entries = min(entries, max_entries, (len(node) - 12) // 12)

    if depth == 0:
        for i in range(entries):
            logical, length, start_hi, start_lo = struct.unpack_from(
                "<IHHI", node, 12 + i * 12)
            if not length:
                continue
            if length & EXT4_EXT_UNWRITTEN:
                # Unwritten (preallocated) extent: reads return zeroes.
                continue
            length &= 0x7FFF
            lo = max(logical, start)
            hi = min(logical + length, end)
            if lo >= hi:
                continue
            physical = (start_hi << 32) | start_lo
            yield lo, physical + (lo - logical), hi - lo
        return

    for i in range(entries):
        logical, leaf_lo, leaf_hi, _unused = struct.unpack_from(
            "<IIHH", node, 12 + i * 12)
        if i + 1 < entries:
            next_logical = _u32(node, 12 + (i + 1) * 12)
        else:
            next_logical = end
        if next_logical <= start or logical >= end:
            continue
        child = reader._block((leaf_hi << 32) | leaf_lo)
        yield from _extent_runs(
            reader, child, max(start, logical), min(end, next_logical),
            depth - 1)


def _indirect_runs(reader: "Ext4Reader", block: int, level: int, base: int,
                   start: int,
                   end: int) -> Iterator[Tuple[int, int, int]]:
    """Walk an indirect block tree; level 1 points straight at data."""
    span = reader._ptrs_per_block ** (level - 1)
    if not block or end <= base or start >= base + span * reader._ptrs_per_block:
        return
    data = reader._block(block)
    first = 0 if start <= base else (start - base) // span
    last = min(reader._ptrs_per_block - 1, (end - 1 - base) // span)
    for i in range(first, last + 1):
        child = _u32(data, i * 4)
        if not child:
            continue
        child_base = base + i * span
        if level == 1:
            yield child_base, child, 1
        else:
            yield from _indirect_runs(
                reader, child, level - 1, child_base, start, end)


def _block_map_runs(reader: "Ext4Reader", i_block: bytes, start: int,
                    end: int) -> Iterator[Tuple[int, int, int]]:
    ptrs = reader._ptrs_per_block
    for i in range(min(12, end)):
        if i >= start:
            block = _u32(i_block, i * 4)
            if block:
                yield i, block, 1
    single_base = 12
    yield from _indirect_runs(
        reader, _u32(i_block, 48), 1, single_base, start, end)
    double_base = single_base + ptrs
    yield from _indirect_runs(
        reader, _u32(i_block, 52), 2, double_base, start, end)
    triple_base = double_base + ptrs * ptrs
    yield from _indirect_runs(
        reader, _u32(i_block, 56), 3, triple_base, start, end)


def _coalesce(runs: Iterator[Tuple[int, int, int]]
              ) -> Iterator[Tuple[int, int, int]]:
    cur_logical = cur_physical = 0
    cur_count = 0
    for logical, physical, count in runs:
        if cur_count and logical == cur_logical + cur_count \
                and physical == cur_physical + cur_count:
            cur_count += count
        else:
            if cur_count:
                yield cur_logical, cur_physical, cur_count
            cur_logical, cur_physical, cur_count = logical, physical, count
    if cur_count:
        yield cur_logical, cur_physical, cur_count


def _data_runs(reader: "Ext4Reader", inode: "_Inode", start: int,
               end: int) -> Iterator[Tuple[int, int, int]]:
    """Contiguous physical runs covering logical blocks [start, end)."""
    if end <= start:
        return
    if inode.flags & INODE_EXTENTS:
        depth = _u16(inode.i_block, 6)
        if depth > EXT4_EXT_MAX_DEPTH:
            raise ValueError(f"inode {inode.ino}: extent depth {depth}")
        yield from _coalesce(
            _extent_runs(reader, inode.i_block, start, end, depth))
    else:
        yield from _coalesce(
            _block_map_runs(reader, inode.i_block, start, end))


def _read_range(reader: "Ext4Reader", inode: "_Inode", offset: int,
                size: int) -> bytes:
    if offset < 0:
        raise ValueError("negative file offset")
    if size <= 0 or offset >= inode.size:
        return b""
    size = min(size, inode.size - offset)
    if inode.inline_data is not None:
        return inode.inline_data[offset:offset + size]
    if inode.is_fast_symlink:
        return inode.i_block[offset:offset + size]

    block_size = reader.block_size
    start = offset // block_size
    end = (offset + size + block_size - 1) // block_size
    out = bytearray(size)
    for logical, physical, count in _data_runs(reader, inode, start, end):
        run_start = logical * block_size
        run_end = (logical + count) * block_size
        lo = max(run_start, offset)
        hi = min(run_end, offset + size)
        if lo >= hi:
            continue
        out[lo - offset:hi - offset] = reader._view.read(
            physical * block_size + (lo - run_start), hi - lo)
    return bytes(out)
