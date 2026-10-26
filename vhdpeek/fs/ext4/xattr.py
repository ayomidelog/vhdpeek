"""Extended-attribute lookup, used for inline data and fast symlinks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .constants import XATTR_MAGIC, _u16, _u32

if TYPE_CHECKING:
    from .reader import Ext4Reader


def _xattr_value(reader: "Ext4Reader", raw: bytes, name: bytes,
                 index: int) -> Optional[bytes]:
    if len(raw) > 128:
        extra = _u16(raw, 128)
        start = 128 + extra
        if 4 <= extra <= len(raw) - 128 and start + 4 <= len(raw) \
                and _u32(raw, start) == XATTR_MAGIC:
            first = start + 4
            value = _scan_xattrs(raw, first, first, len(raw),
                                 name, index)
            if value is not None:
                return value

    acl = _u32(raw, 104) | (_u16(raw, 118) << 32)
    if not acl or acl >= reader.blocks_count:
        return None
    block = reader._block(acl)
    if _u32(block, 0) != XATTR_MAGIC:
        return None
    return _scan_xattrs(block, 32, 0, len(block), name, index)


def _scan_xattrs(buf: bytes, first: int, base: int, end: int,
                 name: bytes, index: int) -> Optional[bytes]:
    """
    Walk the xattr entries at `first`.  `base` is the origin for
    e_value_offs: the first entry for inode-body attributes, the start
    of the block for external ones.
    """
    off = first
    while off + 16 <= end:
        name_len = buf[off]
        if name_len == 0:                       # last entry
            return None
        # e_value_inum != 0 means the value lives in another inode
        if buf[off + 1] != index or _u32(buf, off + 4) \
                or buf[off + 16:off + 16 + name_len] != name:
            off += (16 + name_len + 3) & ~3
            continue
        value_size = _u32(buf, off + 8)
        start = base + _u16(buf, off + 2)
        if start < 0 or start + value_size > end:
            return None
        return buf[start:start + value_size]
    return None
