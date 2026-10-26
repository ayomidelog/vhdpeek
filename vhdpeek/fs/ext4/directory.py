"""Directory blocks, entry lookup and path resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

from ...core.volume import norm_path
from .constants import (
    _DIR_CACHE_MAX_ENTRIES,
    _DIR_CACHE_SIZE,
    _MAX_SYMLINK_HOPS,
    _u16,
    _u32,
)
from .extents import _data_runs, _read_range
from .inode import _inode

if TYPE_CHECKING:
    from .inode import _Inode
    from .reader import Ext4Reader


def _parse_dir_block(reader: "Ext4Reader", block: bytes,
                     out: List[Tuple[int, str, int]]) -> None:
    off = 0
    length = len(block)
    while off + 8 <= length:
        ino = _u32(block, off)
        rec_len = _u16(block, off + 4)
        if reader.has_filetype:
            name_len = block[off + 6]
            file_type = block[off + 7]
        else:
            name_len = _u16(block, off + 6)
            file_type = 0
        if rec_len < 8 or off + rec_len > length:
            break
        # inode 0 covers deleted records, the end of the used area and the
        # metadata_csum tail (name_len 0, file_type 0xDE).
        if ino and name_len and 8 + name_len <= rec_len:
            name = block[off + 8:off + 8 + name_len].decode(
                "utf-8", "replace")
            out.append((ino, name, file_type))
        off += rec_len


def _dir_entries(reader: "Ext4Reader",
                 inode: "_Inode") -> Tuple[Tuple[int, str, int], ...]:
    cached = reader._dirs.get(inode.ino)
    if cached is not None:
        reader._dirs.move_to_end(inode.ino)
        return cached

    block_size = reader.block_size
    blocks = min((inode.size + block_size - 1) // block_size,
                 reader.blocks_count)
    entries: List[Tuple[int, str, int]] = []
    if inode.inline_data is not None:
        # An inline directory starts with the parent inode number.
        _parse_dir_block(reader, inode.inline_data[4:], entries)
        return _cache_dir(reader, inode.ino, entries)
    for logical, physical, count in _data_runs(reader, inode, 0, blocks):
        data = reader._view.read(physical * block_size, count * block_size)
        limit = inode.size - logical * block_size
        if limit < len(data):
            data = data[:limit]
        for pos in range(0, len(data), block_size):
            _parse_dir_block(reader, data[pos:pos + block_size], entries)

    return _cache_dir(reader, inode.ino, entries)


def _cache_dir(reader: "Ext4Reader", ino: int,
               entries: List[Tuple[int, str, int]]
               ) -> Tuple[Tuple[int, str, int], ...]:
    result = tuple(entries)
    if len(result) <= _DIR_CACHE_MAX_ENTRIES:
        reader._dirs[ino] = result
        if len(reader._dirs) > _DIR_CACHE_SIZE:
            reader._dirs.popitem(last=False)
    return result


def _lookup(reader: "Ext4Reader", parent: "_Inode",
            name: str) -> Optional[int]:
    for ino, entry_name, _file_type in _dir_entries(reader, parent):
        if entry_name == name:
            return ino
    return None


def _resolve(reader: "Ext4Reader",
             path: str) -> Optional[Tuple[int, Tuple[str, ...]]]:
    """Follow `path` (including symlinks); return (inode, components)."""
    pending = list(norm_path(path))
    stack: List[Tuple[str, int]] = [("", 2)]
    hops = 0

    while pending:
        name = pending.pop(0)
        if name == "..":
            if len(stack) > 1:
                stack.pop()
            continue
        parent = _inode(reader, stack[-1][1])
        if parent is None or not parent.is_dir:
            return None
        ino = _lookup(reader, parent, name)
        if ino is None:
            return None
        node = _inode(reader, ino)
        if node is None:
            return None
        if node.is_symlink:
            hops += 1
            if hops > _MAX_SYMLINK_HOPS:
                return None
            target = _read_range(reader, node, 0, node.size)
            if not target:
                return None
            text = target.decode("utf-8", "replace")
            if text.startswith("/"):
                stack = [("", 2)]
            pending = list(norm_path(text)) + pending
            continue
        stack.append((name, ino))

    return stack[-1][1], tuple(name for name, _ in stack[1:])
