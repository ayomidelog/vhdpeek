"""
ext2/ext3/ext4 filesystem reader.

Layout, in the order the reader touches it:

  * The superblock starts 1024 bytes into the filesystem.  For a 1 KiB block
    size that is block 1; for every larger block size it is the tail of
    block 0.  It records the block size (1024 << s_log_block_size), the
    geometry (s_blocks_per_group, s_inodes_per_group) and the feature bits
    that decide how inodes and directories are laid out.
  * The volume is split into block groups.  Each group has a descriptor in
    the group descriptor table, which starts in the block after the
    superblock (s_first_data_block + 1).  A descriptor holds the block
    numbers of the block bitmap, the inode bitmap and the inode table.  With
    the 64bit feature the descriptors are s_desc_size (>= 64) bytes wide and
    the high halves of the block numbers follow the 32-bit halves.
  * Inode `n` lives in the table of group (n - 1) / s_inodes_per_group at
    index (n - 1) % s_inodes_per_group, each record s_inode_size bytes.
    The root directory is inode 2.
  * File data is described either by an extent tree in i_block (the
    "extents" incompat feature) or by the classic twelve direct pointers
    plus single/double/triple indirect blocks.  Extent trees are shallow
    (depth <= 5): depth 0 holds leaf extents in the inode itself, deeper
    trees hold index nodes in filesystem blocks.  Unwritten extents and
    holes read as zeroes.
  * Directory data is a sequence of variable-length records
    (inode, rec_len, name_len, file_type, name).  With metadata_csum each
    block ends in a 12-byte tail record whose file_type is 0xDE; records
    with inode 0 are empty and are skipped.  Indexed (htree) directories
    keep their names in ordinary leaf blocks, so a linear scan of the
    directory's data blocks finds every entry.
  * An inode flagged INLINE_DATA keeps its contents in the inode instead
    of in blocks: the first 60 bytes are i_block and the remainder is the
    value of the "system.data" extended attribute, stored in the inode
    body (or in the block named by i_file_acl).  For an inline directory
    the payload starts with the parent inode number, then the same
    directory records as above.

Only the metadata needed for a request is read, and contiguous runs are
fetched with one call, so a multi-gigabyte image stays cheap to browse.
Checksums (metadata_csum, gdt_csum) are not verified: this is a read-only
browser, and a stale checksum should not hide data that is still readable.

bigalloc (cluster allocation, which changes both extent lengths and the
bitmaps) is not supported and is rejected with a clear error rather than
misread.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable, List, Optional, Tuple

from ...core.volume import ByteView, Entry, join_path
from .constants import _BLOCK_CACHE_SIZE
from .directory import _dir_entries, _resolve
from .extents import _read_range
from .inode import _inode, _kind
from .superblock import parse


class Ext4Reader:
    """Read an ext2/ext3/ext4 filesystem through a `ByteView`."""

    def __init__(self, view: ByteView):
        self._view = view
        self._blocks: "OrderedDict[int, bytes]" = OrderedDict()
        self._inodes: "OrderedDict[int, object]" = OrderedDict()
        self._dirs: "OrderedDict[int, Tuple[Tuple[int, str, int], ...]]" = (
            OrderedDict())
        parse(self)

    # ------------------------------------------------------------------
    # Raw block access
    # ------------------------------------------------------------------

    def _block(self, block_no: int) -> bytes:
        cached = self._blocks.get(block_no)
        if cached is not None:
            self._blocks.move_to_end(block_no)
            return cached
        data = self._view.read(block_no * self.block_size, self.block_size)
        self._blocks[block_no] = data
        if len(self._blocks) > _BLOCK_CACHE_SIZE:
            self._blocks.popitem(last=False)
        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_dir(self, path: str = "") -> List[Entry]:
        resolved = _resolve(self, path)
        if resolved is None:
            raise FileNotFoundError(path)
        ino, components = resolved
        parent = _inode(self, ino)
        if parent is None:
            raise FileNotFoundError(path)
        if not parent.is_dir:
            raise NotADirectoryError(path)

        base = "/" + "/".join(components) if components else "/"
        entries: List[Entry] = []
        for child_ino, name, _file_type in _dir_entries(self, parent):
            if name in (".", ".."):
                continue
            child = _inode(self, child_ino)
            if child is None:
                continue
            entries.append(Entry(
                name=name,
                path=join_path(base, name),
                is_dir=child.is_dir,
                size=0 if child.is_dir else child.size,
                mtime=child.mtime,
                extra={"ino": child_ino, "mode": child.mode,
                       "type": _kind(child.mode), "links": child.links},
            ))
        return entries

    def stat(self, path: str) -> Optional[Entry]:
        resolved = _resolve(self, path)
        if resolved is None:
            return None
        ino, components = resolved
        node = _inode(self, ino)
        if node is None:
            return None
        name = components[-1] if components else ""
        return Entry(
            name=name,
            path="/" + "/".join(components) if components else "/",
            is_dir=node.is_dir,
            size=0 if node.is_dir else node.size,
            mtime=node.mtime,
            extra={"ino": ino, "mode": node.mode, "type": _kind(node.mode),
                   "links": node.links},
        )

    def read_file(self, path: str, offset: int = 0,
                  size: Optional[int] = None) -> bytes:
        if offset < 0:
            raise ValueError("negative file offset")
        resolved = _resolve(self, path)
        if resolved is None:
            return b""
        node = _inode(self, resolved[0])
        if node is None or node.is_dir:
            return b""
        if size is None:
            size = node.size - offset
        return _read_range(self, node, offset, size)

    def file_reader(self, path: str) -> Callable[[int, int], bytes]:
        """A (offset, size) -> bytes reader, zero-filled past end of file."""
        resolved = _resolve(self, path)
        node = _inode(self, resolved[0]) if resolved else None
        if node is None or node.is_dir:
            return lambda offset, size: b""

        def reader(offset: int, size: int) -> bytes:
            if offset < 0:
                raise ValueError("negative file offset")
            if size <= 0:
                return b""
            data = _read_range(self, node, offset, size)
            if len(data) < size:
                data += b"\x00" * (size - len(data))
            return data

        return reader
