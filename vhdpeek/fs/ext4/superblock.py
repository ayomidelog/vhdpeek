"""Superblock and block-group descriptor parsing."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from .constants import (
    COMPAT_HAS_JOURNAL,
    COMPAT_SPARSE_SUPER2,
    INCOMPAT_64BIT,
    INCOMPAT_EXTENTS,
    INCOMPAT_FILETYPE,
    INCOMPAT_FLEX_BG,
    INCOMPAT_LARGEDIR,
    INCOMPAT_META_BG,
    INCOMPAT_INLINE_DATA,
    RO_COMPAT_BIGALLOC,
    RO_COMPAT_DIR_NLINK,
    RO_COMPAT_EXTRA_ISIZE,
    RO_COMPAT_GDT_CSUM,
    RO_COMPAT_HUGE_FILE,
    RO_COMPAT_METADATA_CSUM,
    RO_COMPAT_SPARSE_SUPER,
    _u16,
    _u32,
)

if TYPE_CHECKING:
    from .reader import Ext4Reader


def parse(reader: "Ext4Reader") -> None:
    """Validate the superblock and fill in the geometry on `reader`."""
    sb = reader._view.read(1024, 1024)
    if _u16(sb, 56) != 0xEF53:
        raise ValueError(
            f"not an ext2/3/4 filesystem (superblock magic {_u16(sb, 56):#06x})")
    reader._sb = sb

    log_block_size = _u32(sb, 24)
    if log_block_size > 6:
        raise ValueError(f"invalid ext4 block size exponent {log_block_size}")
    reader.block_size = 1024 << log_block_size
    reader._ptrs_per_block = reader.block_size // 4

    reader.inodes_count = _u32(sb, 0)
    reader.blocks_count = _u32(sb, 4)
    reader.first_data_block = _u32(sb, 20)
    reader.blocks_per_group = _u32(sb, 32)
    reader.inodes_per_group = _u32(sb, 40)
    reader.compat = _u32(sb, 92)
    reader.incompat = _u32(sb, 96)
    reader.ro_compat = _u32(sb, 100)

    if reader.incompat & INCOMPAT_64BIT:
        reader.blocks_count |= _u32(sb, 336) << 32

    if reader.ro_compat & RO_COMPAT_BIGALLOC:
        raise ValueError("ext4 bigalloc is not supported")

    rev_level = _u32(sb, 76)
    inode_size = _u16(sb, 88) if rev_level >= 1 else 128
    if inode_size == 0:
        inode_size = 128
    if inode_size < 128 or inode_size > reader.block_size:
        raise ValueError(f"invalid ext4 inode size {inode_size}")
    if reader.block_size % inode_size:
        raise ValueError(
            f"ext4 inode size {inode_size} does not divide the block size")
    reader.inode_size = inode_size

    if not reader.blocks_per_group or not reader.inodes_per_group:
        raise ValueError("ext4 superblock has zero blocks/inodes per group")
    if reader.blocks_count <= reader.first_data_block:
        raise ValueError("ext4 superblock has no data blocks")

    if reader.incompat & INCOMPAT_64BIT:
        desc_size = _u16(sb, 254)
        reader.desc_size = desc_size if desc_size >= 64 else 64
        if reader.desc_size > reader.block_size:
            raise ValueError(f"invalid ext4 descriptor size {reader.desc_size}")
    else:
        reader.desc_size = 32
    reader._descs_per_block = reader.block_size // reader.desc_size
    reader._first_meta_bg = _u32(sb, 260)

    reader.group_count = ((reader.blocks_count - reader.first_data_block
                           + reader.blocks_per_group - 1)
                          // reader.blocks_per_group)

    reader.has_filetype = bool(reader.incompat & INCOMPAT_FILETYPE)
    reader.fs_type = _detect_type(reader)

    label = sb[120:136].split(b"\x00", 1)[0]
    reader.label = label.decode("utf-8", "replace")

    # One allocation unit per block: bigalloc (clusters) is rejected above.
    reader.cluster_size = reader.block_size
    reader.total_clusters = reader.blocks_count
    reader.root_inode = 2


def _detect_type(reader: "Ext4Reader") -> str:
    if (reader.incompat & (INCOMPAT_EXTENTS | INCOMPAT_64BIT
                           | INCOMPAT_META_BG | INCOMPAT_FLEX_BG
                           | INCOMPAT_LARGEDIR | INCOMPAT_INLINE_DATA)
            or reader.ro_compat & (RO_COMPAT_HUGE_FILE | RO_COMPAT_GDT_CSUM
                                   | RO_COMPAT_DIR_NLINK
                                   | RO_COMPAT_EXTRA_ISIZE
                                   | RO_COMPAT_METADATA_CSUM)):
        return "ext4"
    if reader.compat & COMPAT_HAS_JOURNAL:
        return "ext3"
    return "ext2"


def _has_super(reader: "Ext4Reader", group: int) -> bool:
    """True if `group` starts with a superblock/GDT backup copy."""
    if reader.compat & COMPAT_SPARSE_SUPER2:
        backups = struct.unpack_from("<II", reader._sb, 588)
        return group == 0 or group in backups
    if not (reader.ro_compat & RO_COMPAT_SPARSE_SUPER):
        return True
    if group in (0, 1):
        return True
    for base in (3, 5, 7):
        n = group
        while n > 1 and n % base == 0:
            n //= base
        if n == 1:
            return True
    return False


def _desc_block_for_group(reader: "Ext4Reader", group: int) -> int:
    index = group // reader._descs_per_block
    if (not (reader.incompat & INCOMPAT_META_BG)
            or index < reader._first_meta_bg):
        return reader.first_data_block + 1 + index
    # meta_bg: the descriptor block for this meta group sits in the first
    # block of the group that starts the meta group.
    first_group = index * reader._descs_per_block
    block = reader.first_data_block + first_group * reader.blocks_per_group
    return block + 1 if _has_super(reader, first_group) else block


def _group_desc(reader: "Ext4Reader", group: int) -> bytes:
    block = _desc_block_for_group(reader, group)
    offset = (group % reader._descs_per_block) * reader.desc_size
    return reader._block(block)[offset:offset + reader.desc_size]


def _inode_table_block(reader: "Ext4Reader", group: int) -> int:
    desc = _group_desc(reader, group)
    table = _u32(desc, 8)
    if reader.desc_size >= 64:
        table |= _u32(desc, 40) << 32
    if not table or table >= reader.blocks_count:
        return 0
    return table
