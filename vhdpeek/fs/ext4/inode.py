"""Inode records and inode-kind classification."""

from __future__ import annotations

import stat as statlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .constants import (
    INCOMPAT_LARGEDIR,
    INODE_INLINE_DATA,
    XATTR_INDEX_SYSTEM,
    _INODE_CACHE_SIZE,
    _u16,
    _u32,
)
from .superblock import _inode_table_block
from .xattr import _xattr_value

if TYPE_CHECKING:
    from .reader import Ext4Reader


@dataclass
class _Inode:
    """The fields of an inode record that this reader needs."""

    ino: int
    mode: int
    size: int
    mtime: Optional[int]
    links: int
    flags: int
    blocks: int          # i_blocks_lo; only tested for zero
    i_block: bytes       # the 60-byte i_block area (extents or block map)
    inline_data: Optional[bytes] = None

    @property
    def is_dir(self) -> bool:
        return statlib.S_ISDIR(self.mode)

    @property
    def is_symlink(self) -> bool:
        return statlib.S_ISLNK(self.mode)

    @property
    def is_fast_symlink(self) -> bool:
        # A symlink with no allocated block keeps its target in i_block.
        return (self.is_symlink and self.inline_data is None
                and self.size <= 60 and self.blocks == 0)


def _kind(mode: int) -> str:
    return {
        statlib.S_IFREG: "file",
        statlib.S_IFDIR: "dir",
        statlib.S_IFLNK: "symlink",
        statlib.S_IFCHR: "chr",
        statlib.S_IFBLK: "blk",
        statlib.S_IFIFO: "fifo",
        statlib.S_IFSOCK: "sock",
    }.get(statlib.S_IFMT(mode), "unknown")


def _inode(reader: "Ext4Reader", ino: int) -> Optional[_Inode]:
    if ino < 1 or ino > reader.inodes_count:
        return None
    cached = reader._inodes.get(ino)
    if cached is not None:
        reader._inodes.move_to_end(ino)
        return cached

    group, index = divmod(ino - 1, reader.inodes_per_group)
    if group >= reader.group_count:
        return None
    table = _inode_table_block(reader, group)
    if not table:
        return None
    offset = table * reader.block_size + index * reader.inode_size
    block_no, within = divmod(offset, reader.block_size)
    raw = reader._block(block_no)[within:within + reader.inode_size]

    mode = _u16(raw, 0)
    size = _u32(raw, 4)
    if statlib.S_ISREG(mode) or (statlib.S_ISDIR(mode)
                                 and reader.incompat & INCOMPAT_LARGEDIR):
        size |= _u32(raw, 108) << 32
    mtime = _u32(raw, 16)
    flags = _u32(raw, 32)
    node = _Inode(
        ino=ino,
        mode=mode,
        size=size,
        mtime=mtime,
        links=_u16(raw, 26),
        flags=flags,
        blocks=_u32(raw, 28),
        i_block=bytes(raw[40:100]),
    )
    if flags & INODE_INLINE_DATA:
        node.inline_data = _inline_payload(reader, raw, node)
    reader._inodes[ino] = node
    if len(reader._inodes) > _INODE_CACHE_SIZE:
        reader._inodes.popitem(last=False)
    return node


def _inline_payload(reader: "Ext4Reader", raw: bytes, inode: _Inode) -> bytes:
    """
    The inline data area: i_block followed by the value of the
    "system.data" xattr, which lives in the inode body or in the
    block named by i_file_acl.
    """
    body = raw[40:100]
    if inode.size <= len(body):
        return body[:inode.size]
    value = _xattr_value(reader, raw, b"data", XATTR_INDEX_SYSTEM)
    if value is None:
        return body
    return (body + value)[:inode.size]
