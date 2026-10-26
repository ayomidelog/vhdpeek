"""ISO 9660 image generator with Rock Ridge and Joliet support."""

from __future__ import annotations

import struct
from typing import Dict, Sequence, Tuple

from .common import _parent_path, _tree, _walk_dirs, _walk_files

ISO_SECTOR = 2048

def _both16(value: int) -> bytes:
    return struct.pack("<H", value) + struct.pack(">H", value)


def _both32(value: int) -> bytes:
    return struct.pack("<I", value) + struct.pack(">I", value)


def _iso_record(name: bytes, extent: int, size: int, is_dir: bool,
                susp: bytes = b"") -> bytes:
    base = 33 + len(name)
    if base % 2:
        base += 1
    total = base + len(susp)
    if total % 2:
        total += 1
    buf = bytearray(total)
    buf[0] = total
    buf[2:10] = _both32(extent)
    buf[10:18] = _both32(size)
    buf[18:25] = bytes([126, 1, 1, 0, 0, 0, 0])
    buf[25] = 0x02 if is_dir else 0x00
    buf[28:32] = _both16(1)
    buf[32] = len(name)
    buf[33:33 + len(name)] = name
    if susp:
        buf[base:base + len(susp)] = susp
    return bytes(buf)


# The ER identifier is what identifies RRIP; the description and source
# strings are informational and are kept short so the root "." record stays
# within the 255-byte record-length limit.
RRIP_DESCRIPTION = b"ROCK RIDGE"
RRIP_SOURCE = b"VHDPEEK"


def _rock_ridge_sp() -> bytes:
    """SUSP 'SP' entry declaring that SUSP fields follow."""
    return b"SP" + bytes([7, 1, 0xBE, 0xEF, 0])


def _rock_ridge_er() -> bytes:
    """RRIP 'ER' entry: the canonical declaration of Rock Ridge usage."""
    identifier = b"RRIP_1991A"
    description = RRIP_DESCRIPTION
    source = RRIP_SOURCE
    length = 8 + len(identifier) + len(description) + len(source)
    return (b"ER" + bytes([length, 1, len(identifier), len(description),
                           len(source), 1])
            + identifier + description + source)


def _rock_ridge_nm(name: str) -> bytes:
    encoded = name.encode("utf-8")
    return b"NM" + bytes([5 + len(encoded), 1, 0]) + encoded


def _path_table(dirs: Sequence[Tuple[str, dict]], extents: Dict[str, int],
                dir_numbers: Dict[str, int], little_endian: bool,
                joliet: bool) -> bytes:
    """ISO 9660 path table: root first, then one entry per directory."""
    endian = "<" if little_endian else ">"
    out = bytearray()
    for path, _node in dirs:
        if path == "":
            identifier = b"\x00"
        else:
            name = path.rsplit("/", 1)[-1]
            identifier = name.encode("utf-16-be" if joliet else "ascii")
        parent = dir_numbers[_parent_path(path)]
        out.append(len(identifier))
        out.append(0)
        out.extend(struct.pack(endian + "I", extents[path]))
        out.extend(struct.pack(endian + "H", parent))
        out.extend(identifier)
        if len(out) % 2:
            out.append(0)
    return bytes(out)


def build_iso(files: Dict[str, bytes], joliet: bool = True,
              rock_ridge: bool = True, volume_id: str = "TESTISO") -> bytes:
    """ISO 9660 image with path tables, optional Joliet and Rock Ridge."""
    tree = _tree(files)
    dirs = _walk_dirs(tree)
    files_list = _walk_files(tree)
    dir_numbers = {path: index + 1 for index, (path, _) in enumerate(dirs)}

    next_sector = 20
    l_path = next_sector
    next_sector += 1
    m_path = next_sector
    next_sector += 1
    l_path_j = m_path_j = 0
    if joliet:
        l_path_j = next_sector
        next_sector += 1
        m_path_j = next_sector
        next_sector += 1

    dir_extent: Dict[str, int] = {}
    for path, _node in dirs:
        dir_extent[path] = next_sector
        next_sector += 1
    joliet_extent: Dict[str, int] = {}
    if joliet:
        for path, _node in dirs:
            joliet_extent[path] = next_sector
            next_sector += 1
    file_extent: Dict[str, int] = {}
    for path, node in files_list:
        file_extent[path] = next_sector
        next_sector += max(1, (len(node["data"]) + ISO_SECTOR - 1)
                           // ISO_SECTOR)

    total_sectors = next_sector
    image = bytearray(total_sectors * ISO_SECTOR)

    primary_table = _path_table(dirs, dir_extent, dir_numbers, True, False)
    image[l_path * ISO_SECTOR:l_path * ISO_SECTOR + len(primary_table)] = \
        primary_table
    image[m_path * ISO_SECTOR:m_path * ISO_SECTOR + len(primary_table)] = \
        _path_table(dirs, dir_extent, dir_numbers, False, False)
    if joliet:
        joliet_table = _path_table(dirs, joliet_extent, dir_numbers, True, True)
        image[l_path_j * ISO_SECTOR:l_path_j * ISO_SECTOR + len(joliet_table)] = \
            joliet_table
        image[m_path_j * ISO_SECTOR:m_path_j * ISO_SECTOR + len(joliet_table)] = \
            _path_table(dirs, joliet_extent, dir_numbers, False, True)

    def dir_content(path: str, node: dict, use_joliet: bool) -> bytes:
        extents = joliet_extent if use_joliet else dir_extent
        parent = _parent_path(path)
        susp_self = b""
        if rock_ridge and not use_joliet and path == "":
            susp_self = _rock_ridge_sp() + _rock_ridge_er()
        blob = bytearray()
        blob.extend(_iso_record(b"\x00", extents[path], ISO_SECTOR, True,
                                susp_self))
        blob.extend(_iso_record(b"\x01", extents[parent], ISO_SECTOR, True))
        for name, child in sorted(node["children"].items()):
            child_path = f"{path}/{name}" if path else name
            if use_joliet:
                encoded = (name + (";1" if not child["dir"] else "")
                           ).encode("utf-16-be")
                susp = b""
            else:
                encoded = (name + (";1" if not child["dir"] else "")
                           ).encode("ascii")
                susp = _rock_ridge_nm(name) if rock_ridge else b""
            if child["dir"]:
                extent = extents[child_path]
                size = ISO_SECTOR
            else:
                extent = file_extent[child_path]
                size = len(child["data"])
            blob.extend(_iso_record(encoded, extent, size, child["dir"], susp))
        return bytes(blob)

    for path, node in dirs:
        content = dir_content(path, node, False)
        if len(content) > ISO_SECTOR:
            raise ValueError(f"ISO directory {path!r} overflows a sector")
        offset = dir_extent[path] * ISO_SECTOR
        image[offset:offset + len(content)] = content
        if joliet:
            content = dir_content(path, node, True)
            offset = joliet_extent[path] * ISO_SECTOR
            image[offset:offset + len(content)] = content

    for path, node in files_list:
        offset = file_extent[path] * ISO_SECTOR
        image[offset:offset + len(node["data"])] = node["data"]

    pvd = bytearray(ISO_SECTOR)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[8:40] = b"VHDPEEK".ljust(32)
    pvd[40:72] = volume_id.encode("ascii")[:32].ljust(32)
    pvd[80:88] = _both32(total_sectors)
    pvd[120:124] = _both16(1)
    pvd[124:128] = _both16(1)
    pvd[128:132] = _both16(ISO_SECTOR)
    pvd[132:140] = _both32(len(primary_table))
    struct.pack_into("<I", pvd, 140, l_path)
    struct.pack_into(">I", pvd, 148, m_path)
    # The PVD's root directory record field is a fixed 34 bytes; the SUSP
    # "SP" entry belongs in the root directory's own "." record, not here.
    root_record = _iso_record(b"\x00", dir_extent[""], ISO_SECTOR, True)
    assert len(root_record) == 34
    pvd[156:190] = root_record
    pvd[881] = 1
    image[16 * ISO_SECTOR:17 * ISO_SECTOR] = pvd

    terminator = bytearray(ISO_SECTOR)
    terminator[0] = 255
    terminator[1:6] = b"CD001"
    terminator[6] = 1
    image[17 * ISO_SECTOR:18 * ISO_SECTOR] = terminator

    if joliet:
        jvd = bytearray(ISO_SECTOR)
        jvd[0] = 2
        jvd[1:6] = b"CD001"
        jvd[6] = 1
        jvd[8:40] = b"VHDPEEK".ljust(32)
        # 32 bytes is 16 UCS-2 characters; longer ids must be cut,
        # never allowed to push the rest of the descriptor along.
        jvd[40:72] = volume_id.encode("utf-16-be")[:32].ljust(32, b"\x00")
        jvd[80:88] = _both32(total_sectors)
        jvd[88:91] = b"%/E"
        jvd[120:124] = _both16(1)
        jvd[124:128] = _both16(1)
        jvd[128:132] = _both16(ISO_SECTOR)
        jvd[132:140] = _both32(len(joliet_table))
        struct.pack_into("<I", jvd, 140, l_path_j)
        struct.pack_into(">I", jvd, 148, m_path_j)
        jvd[156:190] = _iso_record(b"\x00", joliet_extent[""], ISO_SECTOR, True)
        jvd[881] = 1
        image[18 * ISO_SECTOR:19 * ISO_SECTOR] = jvd
        term = bytearray(ISO_SECTOR)
        term[0] = 255
        term[1:6] = b"CD001"
        term[6] = 1
        image[19 * ISO_SECTOR:20 * ISO_SECTOR] = term

    return bytes(image)
