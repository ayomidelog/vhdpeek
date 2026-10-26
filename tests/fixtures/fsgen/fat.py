"""FAT12/16/32 image generator."""

from __future__ import annotations

import struct
from typing import Dict, Optional, Tuple

from .common import _parent_path, _tree, _walk_dirs, _walk_files

_FAT_EOC = {"fat12": 0xFFF, "fat16": 0xFFFF, "fat32": 0x0FFFFFFF}
_FAT_BITS = {"fat12": 12, "fat16": 16, "fat32": 32}
_VALID_SHORT = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$%'-_@~`!(){}^#&")


def _clean_short(text: str) -> str:
    return "".join(c if c in _VALID_SHORT else "_" for c in text.upper())


def _short_name(name: str, used: set) -> Tuple[bytes, int, bool]:
    """(8.3 bytes, NT lowercase flags, needs_lfn)."""
    base, dot, ext = name.partition(".")
    if not dot:
        base, ext = name, ""
    flags = 0
    if base and base == base.lower() and base != base.upper():
        flags |= 0x08
    if ext and ext == ext.lower() and ext != ext.upper():
        flags |= 0x10

    raw_base, raw_ext = base, ext
    base = _clean_short(base) or "_"
    ext = _clean_short(ext)

    if len(base) > 8 or len(ext) > 3:
        for n in range(1, 1000):
            tail = f"~{n}"
            candidate = (base[:8 - len(tail)] + tail).ljust(8) + ext[:3].ljust(3)
            if candidate not in used:
                break
        else:
            raise ValueError(f"cannot shorten {name!r}")
    else:
        candidate = base.ljust(8) + ext.ljust(3)

    if candidate in used:
        raise ValueError(f"duplicate short name for {name!r}")
    used.add(candidate)

    shown = (raw_base if flags & 0x08 else raw_base.upper())
    shown_ext = (raw_ext if flags & 0x10 else raw_ext.upper())
    rendered = shown + ("." + shown_ext if raw_ext else "")
    needs_lfn = rendered != name or len(raw_base) > 8 or len(raw_ext) > 3
    return candidate.encode("cp437"), flags, needs_lfn


def _lfn_checksum(short: bytes) -> int:
    checksum = 0
    for byte in short:
        checksum = (((checksum & 1) << 7) + (checksum >> 1) + byte) & 0xFF
    return checksum


def _lfn_entries(name: str, short: bytes) -> bytes:
    """Long-filename entries, stored last-chunk-first as the spec requires."""
    units = [ord(c) for c in name]
    if len(units) % 13:
        units.append(0x0000)
        while len(units) % 13:
            units.append(0xFFFF)
    chunks = [units[i:i + 13] for i in range(0, len(units), 13)]
    checksum = _lfn_checksum(short)
    out = bytearray()
    for index in range(len(chunks) - 1, -1, -1):
        seq = index + 1
        if index == len(chunks) - 1:
            seq |= 0x40
        chunk = chunks[index]
        entry = bytearray(32)
        entry[0] = seq
        for i, value in enumerate(chunk[0:5]):
            struct.pack_into("<H", entry, 1 + i * 2, value)
        entry[11] = 0x0F
        entry[13] = checksum
        for i, value in enumerate(chunk[5:11]):
            struct.pack_into("<H", entry, 14 + i * 2, value)
        for i, value in enumerate(chunk[11:13]):
            struct.pack_into("<H", entry, 28 + i * 2, value)
        out.extend(entry)
    return bytes(out)


def _short_entry(short: bytes, attr: int, cluster: int, size: int,
                 nt_flags: int = 0) -> bytes:
    entry = bytearray(32)
    entry[0:11] = short
    entry[11] = attr
    entry[12] = nt_flags
    struct.pack_into("<H", entry, 20, (cluster >> 16) & 0xFFFF)
    struct.pack_into("<H", entry, 26, cluster & 0xFFFF)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


def build_fat(files: Dict[str, bytes], fat_type: str = "fat32",
              bytes_per_sector: int = 512, sectors_per_cluster: int = 1,
              root_entries: int = 512, label: str = "TESTVOL") -> bytes:
    """Build a FAT12/16/32 volume from a {path: bytes} mapping."""
    if fat_type not in _FAT_BITS:
        raise ValueError(f"unknown FAT type {fat_type}")
    cluster_size = bytes_per_sector * sectors_per_cluster
    is32 = fat_type == "fat32"
    reserved = 32 if is32 else 1
    num_fats = 2
    eoc = _FAT_EOC[fat_type]
    root_dir_sectors = 0 if is32 else (
        (root_entries * 32 + bytes_per_sector - 1) // bytes_per_sector)

    tree = _tree(files)
    dirs = _walk_dirs(tree)
    files_list = _walk_files(tree)

    next_cluster = [2]
    chains: Dict[int, int] = {}
    payload: Dict[int, bytes] = {}

    def alloc(count: int) -> int:
        start = next_cluster[0]
        for i in range(count):
            cluster = next_cluster[0]
            next_cluster[0] += 1
            chains[cluster] = cluster + 1 if i < count - 1 else eoc
        return start

    def chain_length(start: int) -> int:
        count = 1
        current = start
        while chains[current] != eoc:
            current = chains[current]
            count += 1
        return count

    def extend(start: int, count: int) -> None:
        current = start
        while chains[current] != eoc:
            current = chains[current]
        for _ in range(count - chain_length(start)):
            new = next_cluster[0]
            next_cluster[0] += 1
            chains[current] = new
            chains[new] = eoc
            current = new

    root_cluster: Optional[int] = alloc(1) if is32 else None
    for path, node in dirs:
        if path:
            node["cluster"] = alloc(1)
    for path, node in files_list:
        node["cluster"] = alloc(max(
            1, (len(node["data"]) + cluster_size - 1) // cluster_size))

    cluster_of = {path: (node["cluster"] if path else (root_cluster or 0))
                  for path, node in dirs}

    def render(node: dict, self_cluster: int, parent_cluster: int,
               is_root: bool) -> bytes:
        used: set = set()
        out = bytearray()
        out.extend(_short_entry(b".          ", 0x10, self_cluster, 0))
        out.extend(_short_entry(b"..         ", 0x10, parent_cluster, 0))
        if is_root:
            out.extend(_short_entry(
                label.upper().ljust(11)[:11].encode("cp437"), 0x08, 0, 0))
        for name, child in sorted(node["children"].items()):
            short, flags, needs_lfn = _short_name(name, used)
            if needs_lfn:
                out.extend(_lfn_entries(name, short))
            attr = 0x10 if child["dir"] else 0x20
            size = 0 if child["dir"] else len(child["data"])
            out.extend(_short_entry(short, attr, child["cluster"], size, flags))
        return bytes(out)

    dir_bytes: Dict[str, bytes] = {}
    for path, node in dirs:
        parent_cluster = 0 if not path else cluster_of[_parent_path(path)]
        dir_bytes[path] = render(node, cluster_of[path], parent_cluster,
                                 path == "")

    for path, node in dirs:
        if path == "" and not is32:
            continue
        need = max(1, (len(dir_bytes[path]) + cluster_size - 1) // cluster_size)
        start = cluster_of[path]
        extend(start, need)
        data = dir_bytes[path] + b"\x00" * (need * cluster_size
                                            - len(dir_bytes[path]))
        for i in range(need):
            payload[start + i] = data[i * cluster_size:(i + 1) * cluster_size]

    for _path, node in files_list:
        data = node["data"]
        count = max(1, (len(data) + cluster_size - 1) // cluster_size)
        start = node["cluster"]
        padded = data + b"\x00" * (count * cluster_size - len(data))
        for i in range(count):
            payload[start + i] = padded[i * cluster_size:(i + 1) * cluster_size]

    total_clusters = next_cluster[0] - 2
    # A volume with fewer than 4085 clusters is FAT12 by definition, so a
    # FAT16 image must be padded out to stay unambiguous.
    if fat_type == "fat16":
        total_clusters = max(total_clusters, 4096)
    fat_sectors = 1
    while True:
        entries = total_clusters + 2
        needed = ((entries * _FAT_BITS[fat_type] + 7) // 8
                  + bytes_per_sector - 1) // bytes_per_sector
        if needed <= fat_sectors:
            break
        fat_sectors = needed

    data_sectors = total_clusters * sectors_per_cluster
    total_sectors = (reserved + num_fats * fat_sectors
                     + root_dir_sectors + data_sectors)
    data_start = (reserved + num_fats * fat_sectors
                  + root_dir_sectors) * bytes_per_sector

    out = bytearray(total_sectors * bytes_per_sector)

    # --- BPB ---------------------------------------------------------------
    bs = bytearray(bytes_per_sector)
    bs[0:3] = b"\xEB\x58\x90" if is32 else b"\xEB\x3C\x90"
    bs[3:11] = b"MSWIN4.1"
    struct.pack_into("<H", bs, 0x0B, bytes_per_sector)
    bs[0x0D] = sectors_per_cluster
    struct.pack_into("<H", bs, 0x0E, reserved)
    bs[0x10] = num_fats
    struct.pack_into("<H", bs, 0x11, 0 if is32 else root_entries)
    struct.pack_into("<H", bs, 0x13,
                     0 if is32 or total_sectors > 0xFFFF else total_sectors)
    bs[0x15] = 0xF8
    struct.pack_into("<H", bs, 0x16, 0 if is32 else fat_sectors)
    struct.pack_into("<H", bs, 0x18, 63)
    struct.pack_into("<H", bs, 0x1A, 255)
    struct.pack_into("<I", bs, 0x1C, 0)
    struct.pack_into("<I", bs, 0x20, 0 if is32 else total_sectors)
    bs[0x24:0x28] = b"\x00" * 4
    if is32:
        struct.pack_into("<I", bs, 0x24, fat_sectors)
        struct.pack_into("<H", bs, 0x28, 0)
        struct.pack_into("<H", bs, 0x2A, 0)
        struct.pack_into("<I", bs, 0x2C, root_cluster)
        struct.pack_into("<H", bs, 0x30, 1)
        struct.pack_into("<H", bs, 0x32, 6)
        struct.pack_into("<I", bs, 0x20, total_sectors)
        struct.pack_into("<H", bs, 0x36, 0)
        bs[0x40] = 0x80
        bs[0x42] = 0x29
        struct.pack_into("<I", bs, 0x43, 0x12345678)
        bs[0x47:0x52] = label.upper().ljust(11)[:11].encode("cp437")
        bs[0x52:0x5A] = b"FAT32   "
    else:
        struct.pack_into("<H", bs, 0x36, 0)
        bs[0x36] = 0x80
        bs[0x38] = 0x29
        struct.pack_into("<I", bs, 0x39, 0x12345678)
        bs[0x3D:0x48] = label.upper().ljust(11)[:11].encode("cp437")
        bs[0x3D + 11:0x3D + 19] = (b"FAT16   " if fat_type == "fat16"
                                   else b"FAT12   ")
    bs[510:512] = b"\x55\xAA"
    out[0:bytes_per_sector] = bs

    if is32:
        fsinfo = bytearray(bytes_per_sector)
        struct.pack_into("<I", fsinfo, 0, 0x41615252)
        struct.pack_into("<I", fsinfo, 484, 0x61417272)
        struct.pack_into("<I", fsinfo, 488, 0xFFFFFFFF)
        struct.pack_into("<I", fsinfo, 492, 0xFFFFFFFF)
        struct.pack_into("<I", fsinfo, 508, 0xAA550000)
        out[bytes_per_sector:2 * bytes_per_sector] = fsinfo

    # --- FAT tables --------------------------------------------------------
    def write_entry(fat: bytearray, index: int, value: int) -> None:
        if fat_type == "fat12":
            off = index * 3 // 2
            if index & 1:
                fat[off] = (fat[off] & 0x0F) | ((value & 0x0F) << 4)
                fat[off + 1] = (value >> 4) & 0xFF
            else:
                fat[off] = value & 0xFF
                fat[off + 1] = (fat[off + 1] & 0xF0) | ((value >> 8) & 0x0F)
        elif fat_type == "fat16":
            struct.pack_into("<H", fat, index * 2, value & 0xFFFF)
        else:
            struct.pack_into("<I", fat, index * 4, value & 0x0FFFFFFF)

    first_entry = {"fat12": 0xFF8, "fat16": 0xFFF8, "fat32": 0x0FFFFFF8}
    for fat_no in range(num_fats):
        fat = bytearray(fat_sectors * bytes_per_sector)
        write_entry(fat, 0, first_entry[fat_type])
        write_entry(fat, 1, eoc)
        for cluster, nxt in chains.items():
            write_entry(fat, cluster, nxt)
        start = (reserved + fat_no * fat_sectors) * bytes_per_sector
        out[start:start + len(fat)] = fat

    if not is32:
        root_off = (reserved + num_fats * fat_sectors) * bytes_per_sector
        content = dir_bytes[""]
        out[root_off:root_off + len(content)] = content

    for cluster, data in payload.items():
        off = data_start + (cluster - 2) * cluster_size
        out[off:off + len(data)] = data

    return bytes(out)


def build_fat12(files: Dict[str, bytes], **kwargs) -> bytes:
    return build_fat(files, "fat12", **kwargs)


def build_fat16(files: Dict[str, bytes], **kwargs) -> bytes:
    return build_fat(files, "fat16", **kwargs)


def build_fat32(files: Dict[str, bytes], **kwargs) -> bytes:
    return build_fat(files, "fat32", **kwargs)
