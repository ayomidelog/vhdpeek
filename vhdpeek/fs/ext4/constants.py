"""Feature bits, layout constants and little-endian helpers for ext4."""

from __future__ import annotations

import struct

# s_feature_compat
COMPAT_HAS_JOURNAL = 0x0004
COMPAT_SPARSE_SUPER2 = 0x0200

# s_feature_incompat
INCOMPAT_FILETYPE = 0x0002
INCOMPAT_META_BG = 0x0010
INCOMPAT_EXTENTS = 0x0040
INCOMPAT_64BIT = 0x0080
INCOMPAT_FLEX_BG = 0x0200
INCOMPAT_LARGEDIR = 0x4000
INCOMPAT_INLINE_DATA = 0x8000

# s_feature_ro_compat
RO_COMPAT_SPARSE_SUPER = 0x0001
RO_COMPAT_HUGE_FILE = 0x0008
RO_COMPAT_GDT_CSUM = 0x0010
RO_COMPAT_DIR_NLINK = 0x0020
RO_COMPAT_EXTRA_ISIZE = 0x0040
RO_COMPAT_BIGALLOC = 0x0200
RO_COMPAT_METADATA_CSUM = 0x0400

# i_flags
INODE_EXTENTS = 0x00080000
INODE_INLINE_DATA = 0x10000000

# extended attributes
XATTR_MAGIC = 0xEA020000
XATTR_INDEX_SYSTEM = 7          # the "system." name prefix

EXT4_EXT_MAGIC = 0xF30A
EXT4_EXT_MAX_DEPTH = 5
EXT4_EXT_UNWRITTEN = 0x8000

_BLOCK_CACHE_SIZE = 64
_INODE_CACHE_SIZE = 4096
_DIR_CACHE_SIZE = 16
_DIR_CACHE_MAX_ENTRIES = 8192
_MAX_SYMLINK_HOPS = 40


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]
