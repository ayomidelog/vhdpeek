"""NTFS image generator."""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Sequence, Tuple

from .common import _parent_path, _tree, _walk_dirs, _walk_files

SECTOR = 512

ATTR_STANDARD_INFORMATION = 0x10
ATTR_FILE_NAME = 0x30
ATTR_DATA = 0x80
ATTR_INDEX_ROOT = 0x90
ATTR_INDEX_ALLOCATION = 0xA0
ATTR_BITMAP = 0xB0
ATTR_END = 0xFFFFFFFF


def _int_bytes(value: int, signed: bool) -> bytes:
    """Minimal-width little-endian integer, as run lists require."""
    width = 1
    while True:
        try:
            raw = value.to_bytes(width, "little", signed=signed)
        except OverflowError:
            width += 1
            continue
        if signed:
            if value < 0:
                if raw[-1] & 0x80:
                    return raw
            elif not raw[-1] & 0x80:
                return raw
        else:
            if not raw[-1] & 0x80:
                return raw
        width += 1


def _runs(runs: Sequence[Tuple[int, Optional[int]]]) -> bytes:
    """Encode (length, lcn) pairs as an NTFS data run list; lcn None = hole."""
    out = bytearray()
    previous = 0
    for length, lcn in runs:
        if lcn is None:
            out.append(0x01)
            out.extend(_int_bytes(length, signed=False))
            continue
        delta = lcn - previous
        length_bytes = _int_bytes(length, signed=False)
        offset_bytes = _int_bytes(delta, signed=True)
        out.append((len(length_bytes) & 0x0F) | ((len(offset_bytes) & 0x0F) << 4))
        out.extend(length_bytes)
        out.extend(offset_bytes)
        previous = lcn
    out.append(0)
    return bytes(out)


def _attr_resident(attr_type: int, value: bytes, attr_id: int,
                   indexed: int = 0, name: str = "") -> bytes:
    encoded = name.encode("utf-16-le")
    # The name (if any) sits at offset 24; the value follows it.
    value_offset = 24 + len(encoded)
    padded = (value_offset + len(value) + 7) & ~7
    buf = bytearray(padded)
    struct.pack_into("<I", buf, 0, attr_type)
    struct.pack_into("<I", buf, 4, padded)
    buf[9] = len(encoded) // 2
    struct.pack_into("<H", buf, 10, 24 if encoded else 0)
    struct.pack_into("<H", buf, 14, attr_id)
    struct.pack_into("<I", buf, 16, len(value))
    struct.pack_into("<H", buf, 20, value_offset)
    buf[22] = indexed
    if encoded:
        buf[24:24 + len(encoded)] = encoded
    buf[value_offset:value_offset + len(value)] = value
    return bytes(buf)


def _attr_nonresident(attr_type: int, runs: Sequence[Tuple[int, Optional[int]]],
                      real_size: int, attr_id: int,
                      cluster_size: int, name: str = "") -> bytes:
    encoded = name.encode("utf-16-le")
    runlist = _runs(runs)
    header = 64 + len(encoded)
    padded = (header + len(runlist) + 7) & ~7
    buf = bytearray(padded)
    struct.pack_into("<I", buf, 0, attr_type)
    struct.pack_into("<I", buf, 4, padded)
    buf[8] = 1
    buf[9] = len(encoded) // 2
    struct.pack_into("<H", buf, 10, 64 if encoded else 0)
    struct.pack_into("<H", buf, 14, attr_id)
    struct.pack_into("<Q", buf, 16, 0)
    struct.pack_into("<Q", buf, 24, len(runs) - 1)
    struct.pack_into("<H", buf, 32, header)
    allocated = sum(length for length, _ in runs) * cluster_size
    struct.pack_into("<Q", buf, 40, allocated)
    struct.pack_into("<Q", buf, 48, real_size)
    struct.pack_into("<Q", buf, 56, real_size)
    if encoded:
        buf[64:64 + len(encoded)] = encoded
    buf[header:header + len(runlist)] = runlist
    return bytes(buf)


def _file_name_value(parent: int, name: str, size: int, is_dir: bool,
                     allocated: int = 0) -> bytes:
    encoded = name.encode("utf-16-le")
    value = bytearray(0x42 + len(encoded))
    struct.pack_into("<Q", value, 0x00, parent)
    struct.pack_into("<Q", value, 0x28, allocated or size)
    struct.pack_into("<Q", value, 0x30, size)
    struct.pack_into("<I", value, 0x38, 0x10000000 if is_dir else 0x20)
    value[0x40] = len(encoded) // 2
    value[0x41] = 3                                   # Win32 and DOS namespace
    value[0x42:] = encoded
    return bytes(value)


def _index_entry(file_ref: int, key: bytes, last: bool = False,
                 subnode: Optional[int] = None) -> bytes:
    flags = 0
    if last:
        flags |= 0x02
    if subnode is not None:
        flags |= 0x01
    length = 16 + len(key) + (8 if subnode is not None else 0)
    length = (length + 7) & ~7
    buf = bytearray(length)
    struct.pack_into("<Q", buf, 0, file_ref)
    struct.pack_into("<H", buf, 8, length)
    struct.pack_into("<H", buf, 10, len(key))
    struct.pack_into("<H", buf, 12, flags)
    buf[16:16 + len(key)] = key
    if subnode is not None:
        struct.pack_into("<Q", buf, length - 8, subnode)
    return bytes(buf)


def _index_root(entries: Sequence[bytes], block_size: int,
                subnode: Optional[int] = None) -> bytes:
    blob = b"".join(entries)
    blob += _index_entry(0, b"", last=True, subnode=subnode)
    value = bytearray(32 + len(blob))
    struct.pack_into("<I", value, 0, ATTR_FILE_NAME)
    struct.pack_into("<I", value, 4, 1)               # COLLATION_FILE_NAME
    struct.pack_into("<I", value, 8, block_size)
    value[12] = 1
    struct.pack_into("<I", value, 16, 0x10)
    struct.pack_into("<I", value, 20, 16 + len(blob))
    struct.pack_into("<I", value, 24, 16 + len(blob))
    struct.pack_into("<I", value, 28, 0)
    value[32:] = blob
    return bytes(value)


def _apply_fixup(buf: bytearray, usa_offset: int) -> None:
    sector_count = len(buf) // 512
    struct.pack_into("<H", buf, usa_offset, 0x0001)
    for i in range(sector_count):
        end = (i + 1) * 512 - 2
        original = struct.unpack_from("<H", buf, end)[0]
        struct.pack_into("<H", buf, usa_offset + 2 + i * 2, original)
        struct.pack_into("<H", buf, end, 0x0001)


def _file_record(attributes: Sequence[bytes], is_dir: bool,
                 sequence: int = 1) -> bytes:
    rec = bytearray(1024)
    rec[0:4] = b"FILE"
    usa_offset = 0x30
    usa_count = 1 + len(rec) // 512
    struct.pack_into("<H", rec, 4, usa_offset)
    struct.pack_into("<H", rec, 6, usa_count)
    struct.pack_into("<H", rec, 16, sequence)
    struct.pack_into("<H", rec, 18, 1)
    attr_offset = (usa_offset + 2 + (usa_count - 1) * 2 + 7) & ~7
    struct.pack_into("<H", rec, 20, attr_offset)
    struct.pack_into("<H", rec, 22, 0x01 | (0x02 if is_dir else 0x00))
    struct.pack_into("<I", rec, 28, len(rec))

    offset = attr_offset
    for attr in attributes:
        if offset + len(attr) + 8 > len(rec):
            raise ValueError(
                "MFT record overflow: this entry needs $INDEX_ALLOCATION or "
                "an $ATTRIBUTE_LIST")
        rec[offset:offset + len(attr)] = attr
        offset += len(attr)
    struct.pack_into("<I", rec, offset, ATTR_END)
    offset += 8
    struct.pack_into("<I", rec, 24, offset)
    struct.pack_into("<H", rec, 40, 0x100 + len(attributes))
    _apply_fixup(rec, usa_offset)
    return bytes(rec)


def _indx_block(vcn: int, entries: Sequence[bytes], block_size: int) -> bytes:
    buf = bytearray(block_size)
    buf[0:4] = b"INDX"
    usa_offset = 0x28
    struct.pack_into("<H", buf, 4, usa_offset)
    struct.pack_into("<H", buf, 6, 1 + block_size // 512)
    struct.pack_into("<Q", buf, 16, vcn)
    blob = b"".join(entries) + _index_entry(0, b"", last=True)
    header = 24
    struct.pack_into("<I", buf, header, 0x28)
    struct.pack_into("<I", buf, header + 4, 0x28 + len(blob))
    struct.pack_into("<I", buf, header + 8, block_size - header)
    struct.pack_into("<I", buf, header + 12, 0)
    buf[header + 0x28:header + 0x28 + len(blob)] = blob
    _apply_fixup(buf, usa_offset)
    return bytes(buf)


def build_ntfs(files: Dict[str, bytes], cluster_size: int = 4096,
               total_clusters: int = 2048,
               index_block_size: int = 4096) -> bytes:
    """Build a structurally correct NTFS volume with MFT, runs and indexes."""
    tree = _tree(files)
    dirs = _walk_dirs(tree)
    files_list = _walk_files(tree)

    mft_of: Dict[str, int] = {"": 5}
    next_mft = 6
    for path, _node in dirs[1:]:
        mft_of[path] = next_mft
        next_mft += 1
    for path, _node in files_list:
        mft_of[path] = next_mft
        next_mft += 1
    record_count = next_mft + 2

    mft_cluster = 4
    mft_bytes = record_count * 1024
    mft_clusters = (mft_bytes + cluster_size - 1) // cluster_size
    mirror_cluster = mft_cluster + mft_clusters
    next_free = mirror_cluster + mft_clusters

    for _path, node in files_list:
        data = node["data"]
        node["resident"] = len(data) <= 448
        if not node["resident"]:
            count = (len(data) + cluster_size - 1) // cluster_size
            node["lcn"] = next_free
            node["clusters"] = count
            next_free += count

    index_blocks: Dict[str, int] = {}
    for path, node in dirs:
        if len(node["children"]) > 8:
            index_blocks[path] = next_free
            next_free += (index_block_size + cluster_size - 1) // cluster_size

    total_clusters = max(total_clusters, next_free + 8)
    disk = bytearray(total_clusters * cluster_size)

    boot = bytearray(SECTOR)
    boot[0:3] = b"\xEB\x52\x90"
    boot[3:11] = b"NTFS    "
    struct.pack_into("<H", boot, 0x0B, SECTOR)
    boot[0x0D] = cluster_size // SECTOR
    struct.pack_into("<Q", boot, 0x28, total_clusters)
    struct.pack_into("<Q", boot, 0x30, mft_cluster)
    struct.pack_into("<Q", boot, 0x38, mirror_cluster)
    boot[0x40] = 0xF6                                 # -10 -> 1024-byte records
    boot[0x44] = 1
    struct.pack_into("<Q", boot, 0x48, 0x1122334455667788)
    boot[510:512] = b"\x55\xAA"
    disk[0:SECTOR] = boot

    records: Dict[int, bytes] = {}
    records[0] = _file_record([
        _attr_resident(ATTR_STANDARD_INFORMATION, b"\x00" * 72, 0),
        _attr_resident(ATTR_FILE_NAME,
                       _file_name_value(5, "$MFT", mft_bytes, False), 1),
        _attr_nonresident(ATTR_DATA, [(mft_clusters, mft_cluster)],
                          mft_bytes, 2, cluster_size),
    ], False)

    def dir_attributes(path: str, node: dict) -> List[bytes]:
        children = node["children"]
        parent_mft = mft_of[_parent_path(path)]
        entries: List[bytes] = []
        for name, child in sorted(children.items()):
            child_path = f"{path}/{name}" if path else name
            size = 0 if child["dir"] else len(child["data"])
            key = _file_name_value(parent_mft, name, size, child["dir"])
            entries.append(_index_entry(mft_of[child_path], key))

        subnode = index_blocks.get(path)
        root = _index_root([] if subnode is not None else entries,
                           index_block_size, subnode)
        attrs = [
            _attr_resident(ATTR_STANDARD_INFORMATION, b"\x00" * 72, 0),
            _attr_resident(ATTR_FILE_NAME,
                           _file_name_value(parent_mft,
                                            path.rsplit("/", 1)[-1] or ".",
                                            len(children), True), 1),
            _attr_resident(ATTR_INDEX_ROOT, root, 2, indexed=1,
                           name="$I30"),
        ]
        if subnode is not None:
            blocks = (index_block_size + cluster_size - 1) // cluster_size
            attrs.append(_attr_nonresident(ATTR_INDEX_ALLOCATION,
                                           [(blocks, subnode)],
                                           index_block_size, 3, cluster_size,
                                           name="$I30"))
            attrs.append(_attr_resident(ATTR_BITMAP, b"\x01\x00\x00\x00", 4,
                                        name="$I30"))
        return attrs

    for path, node in dirs:
        records[mft_of[path]] = _file_record(
            dir_attributes(path, node), True)

    for path, node in files_list:
        data = node["data"]
        parent_mft = mft_of[_parent_path(path)]
        attrs = [
            _attr_resident(ATTR_STANDARD_INFORMATION, b"\x00" * 72, 0),
            _attr_resident(ATTR_FILE_NAME,
                           _file_name_value(parent_mft,
                                            path.rsplit("/", 1)[-1],
                                            len(data), False), 1),
        ]
        if node["resident"]:
            attrs.append(_attr_resident(ATTR_DATA, data, 2))
        else:
            attrs.append(_attr_nonresident(
                ATTR_DATA, [(node["clusters"], node["lcn"])],
                len(data), 2, cluster_size))
            padded = data + b"\x00" * (-len(data) % cluster_size)
            offset = node["lcn"] * cluster_size
            disk[offset:offset + len(padded)] = padded
        records[mft_of[path]] = _file_record(attrs, False)

    for mft_no, record in records.items():
        offset = mft_cluster * cluster_size + mft_no * 1024
        disk[offset:offset + 1024] = record
    for mft_no in range(4):
        offset = mirror_cluster * cluster_size + mft_no * 1024
        disk[offset:offset + 1024] = records.get(
            mft_no, _file_record([], False))

    for path, lcn in index_blocks.items():
        node = dict(dirs)[path]
        parent_mft = mft_of[_parent_path(path)]
        entries: List[bytes] = []
        for name, child in sorted(node["children"].items()):
            child_path = f"{path}/{name}" if path else name
            size = 0 if child["dir"] else len(child["data"])
            key = _file_name_value(parent_mft, name, size, child["dir"])
            entries.append(_index_entry(mft_of[child_path], key))
        block = _indx_block(0, entries, index_block_size)
        offset = lcn * cluster_size
        disk[offset:offset + len(block)] = block

    return bytes(disk)
