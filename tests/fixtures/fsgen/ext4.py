"""ext2/3/4 image generator."""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Sequence, Tuple

from .common import _parent_path, _tree, _walk_dirs, _walk_files

EXT4_EXTENTS_FL = 0x00080000
EXT4_INCOMPAT_FILETYPE = 0x0002
EXT4_INCOMPAT_EXTENTS = 0x0040
EXT4_INCOMPAT_64BIT = 0x0080


def _extent_entries(runs: Sequence[Tuple[int, int, int]]) -> bytes:
    body = bytearray()
    for logical, count, physical in runs:
        entry = bytearray(12)
        struct.pack_into("<I", entry, 0, logical)
        struct.pack_into("<H", entry, 4, count)
        struct.pack_into("<H", entry, 6, (physical >> 32) & 0xFFFF)
        struct.pack_into("<I", entry, 8, physical & 0xFFFFFFFF)
        body.extend(entry)
    return bytes(body)


def build_ext4(files: Dict[str, bytes], block_size: int = 4096,
               inodes_per_group: int = 64,
               inode_size: int = 256) -> bytes:
    """
    Build an ext4 image with 64-bit group descriptors, filetype directory
    entries and extent trees at depth 0 and depth 1.
    """
    tree = _tree(files)
    dirs = _walk_dirs(tree)
    files_list = _walk_files(tree)

    ino_of: Dict[str, int] = {"": 2}
    next_ino = 11
    for path, _node in dirs[1:]:
        ino_of[path] = next_ino
        next_ino += 1
    for path, _node in files_list:
        ino_of[path] = next_ino
        next_ino += 1

    gdt_block = 1
    block_bitmap_block = 2
    inode_bitmap_block = 3
    inode_table_block = 4
    inode_table_blocks = (inodes_per_group * inode_size
                          + block_size - 1) // block_size
    next_block = inode_table_block + inode_table_blocks

    def alloc(count: int = 1) -> List[int]:
        nonlocal next_block
        blocks = list(range(next_block, next_block + count))
        next_block += count
        return blocks

    dir_blocks: Dict[str, List[int]] = {path: alloc(1) for path, _ in dirs}

    file_blocks: Dict[str, List[int]] = {}
    for index, (path, node) in enumerate(files_list):
        count = max(1, (len(node["data"]) + block_size - 1) // block_size)
        if index % 2 == 1 and count > 2:
            # Fragment this file so it needs more than four extents.
            blocks = alloc(1) + alloc(1) + alloc(count - 1)
        else:
            blocks = alloc(count)
        file_blocks[path] = blocks

    # --- extent trees (leaf blocks allocated before the image is sized) ----
    extents: Dict[str, bytes] = {}
    leaves: List[Tuple[int, bytes]] = []
    all_blocks = dict(dir_blocks)
    all_blocks.update(file_blocks)
    for path, blocks in all_blocks.items():
        runs: List[Tuple[int, int, int]] = []
        for logical, physical in enumerate(blocks):
            if runs and runs[-1][0] + runs[-1][1] == logical \
                    and runs[-1][2] + runs[-1][1] == physical:
                logical0, count, physical0 = runs[-1]
                runs[-1] = (logical0, count + 1, physical0)
            else:
                runs.append((logical, 1, physical))

        header = bytearray(12)
        struct.pack_into("<H", header, 0, 0xF30A)
        struct.pack_into("<I", header, 8, 0)
        if len(runs) <= 4:
            struct.pack_into("<H", header, 2, len(runs))
            struct.pack_into("<H", header, 4, 4)
            struct.pack_into("<H", header, 6, 0)
            extents[path] = bytes(header) + _extent_entries(runs)
        else:
            leaf_block = alloc(1)[0]
            leaf = bytearray(12)
            struct.pack_into("<H", leaf, 0, 0xF30A)
            struct.pack_into("<H", leaf, 2, len(runs))
            struct.pack_into("<H", leaf, 4, (block_size - 12) // 12)
            struct.pack_into("<H", leaf, 6, 0)
            struct.pack_into("<I", leaf, 8, 0)
            leaf += _extent_entries(runs)
            struct.pack_into("<H", header, 2, 1)
            struct.pack_into("<H", header, 4, 4)
            struct.pack_into("<H", header, 6, 1)
            index = bytearray(12)
            struct.pack_into("<I", index, 0, 0)
            struct.pack_into("<I", index, 4, leaf_block & 0xFFFFFFFF)
            struct.pack_into("<H", index, 8, (leaf_block >> 32) & 0xFFFF)
            extents[path] = bytes(header) + bytes(index)
            leaves.append((leaf_block, bytes(leaf)))

    total_blocks = next_block + 8
    image = bytearray(total_blocks * block_size)

    inode_table = bytearray(inodes_per_group * inode_size)

    def set_inode(ino: int, mode: int, size: int, is_dir: bool,
                  block_count: int, extent_blob: Optional[bytes]) -> None:
        base = (ino - 1) * inode_size
        struct.pack_into("<H", inode_table, base + 0x00, mode)
        struct.pack_into("<I", inode_table, base + 0x04, size & 0xFFFFFFFF)
        struct.pack_into("<I", inode_table, base + 0x6C, size >> 32)
        struct.pack_into("<H", inode_table, base + 0x1A, 2 if is_dir else 1)
        struct.pack_into("<I", inode_table, base + 0x1C,
                         block_count * (block_size // 512))
        struct.pack_into("<I", inode_table, base + 0x20, EXT4_EXTENTS_FL)
        if extent_blob:
            inode_table[base + 0x28:base + 0x28 + len(extent_blob)] = extent_blob

    def render_dir(path: str, node: dict, self_ino: int,
                   parent_ino: int) -> bytes:
        entries: List[Tuple[int, str, int]] = [
            (self_ino, ".", 2), (parent_ino, "..", 2)]
        for name, child in sorted(node["children"].items()):
            child_path = f"{path}/{name}" if path else name
            entries.append((ino_of[child_path], name,
                            2 if child["dir"] else 1))
        blob = bytearray()
        for i, (ino, name, dtype) in enumerate(entries):
            encoded = name.encode("utf-8")
            rec_len = (8 + len(encoded) + 3) & ~3
            if i == len(entries) - 1:
                rec_len = block_size - len(blob)
            entry = bytearray(rec_len)
            struct.pack_into("<I", entry, 0, ino)
            struct.pack_into("<H", entry, 4, rec_len)
            entry[6] = len(encoded)
            entry[7] = dtype
            entry[8:8 + len(encoded)] = encoded
            blob.extend(entry)
        return bytes(blob)

    for path, node in dirs:
        parent_ino = ino_of[_parent_path(path)] if path else 2
        content = render_dir(path, node, ino_of[path], parent_ino)
        if len(content) > block_size:
            raise ValueError(f"directory {path!r} overflows one block")
        offset = dir_blocks[path][0] * block_size
        image[offset:offset + len(content)] = content
        set_inode(ino_of[path], 0o040755, len(content), True,
                  len(dir_blocks[path]), extents[path])

    for path, node in files_list:
        data = node["data"]
        blocks = file_blocks[path]
        set_inode(ino_of[path], 0o100644, len(data), False,
                  len(blocks), extents[path])
        for i, block in enumerate(blocks):
            chunk = data[i * block_size:(i + 1) * block_size]
            if not chunk:
                break
            offset = block * block_size
            image[offset:offset + len(chunk)] = chunk

    for leaf_block, leaf_data in leaves:
        offset = leaf_block * block_size
        image[offset:offset + len(leaf_data)] = leaf_data

    set_inode(1, 0o100644, 0, False, 0, None)

    # --- superblock --------------------------------------------------------
    sb = bytearray(1024)
    struct.pack_into("<I", sb, 0x00, inodes_per_group)
    struct.pack_into("<I", sb, 0x04, total_blocks)
    struct.pack_into("<I", sb, 0x0C, 0)
    struct.pack_into("<I", sb, 0x10, 0)
    struct.pack_into("<I", sb, 0x14, 0)               # first data block
    struct.pack_into("<I", sb, 0x18, 2)               # log block size -> 4 KiB
    struct.pack_into("<I", sb, 0x1C, 2)
    struct.pack_into("<I", sb, 0x20, 8 * block_size)  # blocks per group
    struct.pack_into("<I", sb, 0x24, 8 * block_size)
    struct.pack_into("<I", sb, 0x28, inodes_per_group)
    struct.pack_into("<H", sb, 0x34, 1)
    struct.pack_into("<H", sb, 0x36, 0xFFFF)
    struct.pack_into("<H", sb, 0x38, 0xEF53)
    struct.pack_into("<H", sb, 0x3A, 1)
    struct.pack_into("<H", sb, 0x3C, 1)
    struct.pack_into("<I", sb, 0x4C, 1)               # dynamic revision
    struct.pack_into("<I", sb, 0x54, 11)              # first non-reserved inode
    struct.pack_into("<H", sb, 0x58, inode_size)
    struct.pack_into("<I", sb, 0x5C, 0x0001 | 0x0004)  # dir_index, has_journal
    struct.pack_into("<I", sb, 0x60, EXT4_INCOMPAT_FILETYPE
                     | EXT4_INCOMPAT_EXTENTS | EXT4_INCOMPAT_64BIT)
    struct.pack_into("<I", sb, 0x64, 0x0001 | 0x0002)  # sparse_super, large_file
    sb[0x68:0x78] = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
    sb[0x78:0x80] = b"TESTVOL\x00"
    struct.pack_into("<H", sb, 0xFE, 64)
    image[1024:1024 + 1024] = sb

    gd = bytearray(64)
    struct.pack_into("<I", gd, 0x00, block_bitmap_block)
    struct.pack_into("<I", gd, 0x04, inode_bitmap_block)
    struct.pack_into("<I", gd, 0x08, inode_table_block)
    image[gdt_block * block_size:gdt_block * block_size + len(gd)] = gd

    bitmap = bytearray(block_size)
    for block in range(total_blocks):
        if block < next_block:
            bitmap[block // 8] |= 1 << (block % 8)
    image[block_bitmap_block * block_size:
          block_bitmap_block * block_size + block_size] = bitmap

    inode_bitmap = bytearray(block_size)
    for ino in range(1, next_ino):
        inode_bitmap[(ino - 1) // 8] |= 1 << ((ino - 1) % 8)
    image[inode_bitmap_block * block_size:
          inode_bitmap_block * block_size + block_size] = inode_bitmap

    table_offset = inode_table_block * block_size
    image[table_offset:table_offset + len(inode_table)] = inode_table

    return bytes(image)
