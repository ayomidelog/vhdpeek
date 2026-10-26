"""Generate VHD / VHDX containers and partition tables for the test suite.

Every structure here follows the published layout, because the parser is
verified against these images:

  fixed VHD   raw disk data at offset 0, 512-byte footer appended
  dynamic VHD footer copy, "cxsparse" header, BAT, blocks with sector
              bitmaps, footer
  VHDX        "vhdxfile" id, two "head" headers, two "regi" region tables,
              BAT region, metadata region, data blocks
"""

from __future__ import annotations

import struct
import uuid
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

SECTOR = 512

# VHDX identifiers, in on-disk (little-endian mixed) byte order.
GUID_BAT = "2DC27766-F623-4200-9D64-115E9BFD4A08"
GUID_METADATA = "8B7CA206-4790-4B9A-B8FE-575F050F886E"
GUID_FILE_PARAMETERS = "CAA16737-FA36-4D43-B3B6-33F0AA44E76B"
GUID_VIRTUAL_SIZE = "2FA54224-CD1B-4876-B211-5DBED83BF4B8"
GUID_LOGICAL_SECTOR = "8141BF1D-A96F-4709-BA47-F233A8FAAB5F"
GUID_PHYSICAL_SECTOR = "CDA348C7-445D-4471-9CC9-E9885251C556"
GUID_VIRTUAL_DISK_ID = "BECA12AB-B2E6-4523-93EF-C309E000C746"


def guid_bytes(text: str) -> bytes:
    """Canonical GUID string -> 16 on-disk bytes."""
    return uuid.UUID(text).bytes_le


# ---------------------------------------------------------------------------
# Partition tables
# ---------------------------------------------------------------------------

def build_mbr(partitions: Sequence[Tuple[int, int, int, str]]) -> bytes:
    """
    partitions: [(start_lba, sector_count, mbr_type, name), ...]

    Logical partitions are expressed by passing an extended type (0x05/0x0F)
    for the container and listing logicals separately via `build_ebr_chain`.
    """
    mbr = bytearray(SECTOR)
    mbr[510:512] = b"\x55\xAA"
    for i, (start, count, ptype, _name) in enumerate(partitions[:4]):
        off = 446 + i * 16
        mbr[off + 4] = ptype
        struct.pack_into("<I", mbr, off + 8, start)
        struct.pack_into("<I", mbr, off + 12, count)
    return bytes(mbr)


def build_ebr(logical_start: int, logical_count: int, ptype: int,
              next_ebr_relative: Optional[int] = None) -> bytes:
    """One extended boot record: a logical partition, plus the chain link."""
    ebr = bytearray(SECTOR)
    ebr[510:512] = b"\x55\xAA"
    off = 446
    ebr[off + 4] = ptype
    struct.pack_into("<I", ebr, off + 8, logical_start)
    struct.pack_into("<I", ebr, off + 12, logical_count)
    if next_ebr_relative is not None:
        off = 446 + 16
        ebr[off + 4] = 0x0F
        struct.pack_into("<I", ebr, off + 8, next_ebr_relative)
        struct.pack_into("<I", ebr, off + 12, 1)
    return bytes(ebr)


def build_gpt(disk_sectors: int,
              partitions: Sequence[Tuple[int, int, str, str]]) -> bytes:
    """
    Protective MBR + GPT header + entry array.

    partitions: [(first_lba, last_lba, type_guid, name), ...]
    Returns bytes covering LBA 0..33.
    """
    entry_count = 128
    entry_size = 128
    entries_sectors = entry_count * entry_size // SECTOR
    first_usable = 2 + entries_sectors
    last_usable = disk_sectors - first_usable
    disk_guid = uuid.UUID("12345678-1234-5678-9ABC-DEF012345678").bytes_le

    # Protective MBR: a single 0xEE entry spanning the disk.
    mbr = build_mbr([(1, min(disk_sectors - 1, 0xFFFFFFFF), 0xEE, "GPT")])

    header = bytearray(SECTOR)
    header[0:8] = b"EFI PART"
    struct.pack_into("<I", header, 8, 0x00010000)
    struct.pack_into("<I", header, 12, 92)
    struct.pack_into("<Q", header, 24, 1)              # current LBA
    struct.pack_into("<Q", header, 32, disk_sectors - 1)  # backup LBA
    struct.pack_into("<Q", header, 40, first_usable)
    struct.pack_into("<Q", header, 48, last_usable)
    header[56:72] = disk_guid
    struct.pack_into("<Q", header, 72, 2)              # entry array LBA
    struct.pack_into("<I", header, 80, entry_count)
    struct.pack_into("<I", header, 84, entry_size)

    entries = bytearray(entry_count * entry_size)
    for i, (first, last, type_guid, name) in enumerate(partitions):
        off = i * entry_size
        entries[off:off + 16] = guid_bytes(type_guid)
        entries[off + 16:off + 32] = uuid.uuid4().bytes_le
        struct.pack_into("<Q", entries, off + 32, first)
        struct.pack_into("<Q", entries, off + 40, last)
        encoded = name.encode("utf-16-le")
        entries[off + 56:off + 56 + len(encoded)] = encoded

    struct.pack_into("<I", header, 88, zlib.crc32(bytes(entries)) & 0xFFFFFFFF)
    struct.pack_into("<I", header, 16, 0)
    struct.pack_into("<I", header, 16, zlib.crc32(bytes(header)) & 0xFFFFFFFF)

    return mbr + bytes(header) + bytes(entries)


# ---------------------------------------------------------------------------
# VHD
# ---------------------------------------------------------------------------

def _vhd_footer(disk_type: int, current_size: int,
                data_offset: int) -> bytes:
    ftr = bytearray(SECTOR)
    ftr[0:8] = b"conectix"
    struct.pack_into(">I", ftr, 8, 2)                  # features: reserved bit
    struct.pack_into(">I", ftr, 12, 0x00010000)        # version 1.0
    struct.pack_into(">Q", ftr, 16, data_offset)
    struct.pack_into(">I", ftr, 24, 0)                 # timestamp
    ftr[28:32] = b"vhdu"
    struct.pack_into(">I", ftr, 32, 0x00010000)
    ftr[36:40] = b"Wi2k"
    struct.pack_into(">Q", ftr, 40, current_size)      # disk size
    struct.pack_into(">Q", ftr, 48, current_size)      # data size
    struct.pack_into(">I", ftr, 56, 0)                 # geometry
    struct.pack_into(">I", ftr, 60, disk_type)
    ftr[68:84] = uuid.uuid5(uuid.NAMESPACE_DNS, "vhdpeek").bytes
    struct.pack_into(">I", ftr, 64, 0)
    checksum = (~sum(ftr)) & 0xFFFFFFFF
    struct.pack_into(">I", ftr, 64, checksum)
    return bytes(ftr)


def wrap_fixed_vhd(data: bytes) -> bytes:
    """Fixed VHD: the disk data starts at file offset 0."""
    padded = bytes(data) + b"\x00" * (-len(data) % SECTOR)
    return padded + _vhd_footer(2, len(padded), 0xFFFFFFFFFFFFFFFF)


def wrap_dynamic_vhd(data: bytes, block_size: int = 2 << 20) -> bytes:
    """
    Dynamic VHD: footer copy, 1024-byte "cxsparse" header, BAT, then blocks
    of a 512-byte sector bitmap followed by `block_size` bytes of data.
    """
    virtual_size = len(data) + (-len(data) % SECTOR)
    padded = bytes(data) + b"\x00" * (virtual_size - len(data))
    total_blocks = (virtual_size + block_size - 1) // block_size
    stored = padded + b"\x00" * (total_blocks * block_size - len(padded))
    bitmap_size = 512

    header_offset = SECTOR
    bat_offset = header_offset + 1024
    bat_bytes = total_blocks * 4
    blocks_offset = bat_offset + bat_bytes
    blocks_offset += -blocks_offset % SECTOR

    bat = bytearray(total_blocks * 4)
    body = bytearray()
    for i in range(total_blocks):
        file_block = blocks_offset + i * (bitmap_size + block_size)
        struct.pack_into(">I", bat, i * 4, file_block // SECTOR)
        body.extend(b"\xFF" * bitmap_size)
        body.extend(stored[i * block_size:(i + 1) * block_size])

    hdr = bytearray(1024)
    hdr[0:8] = b"cxsparse"
    struct.pack_into(">Q", hdr, 8, 0xFFFFFFFFFFFFFFFF)
    struct.pack_into(">Q", hdr, 16, bat_offset)
    struct.pack_into(">I", hdr, 24, 0x00010000)
    struct.pack_into(">I", hdr, 28, total_blocks)
    struct.pack_into(">I", hdr, 32, block_size)
    hdr[40:56] = b"\x00" * 16

    footer = _vhd_footer(3, virtual_size, header_offset)
    pad = b"\x00" * (blocks_offset - (bat_offset + bat_bytes))
    return footer + bytes(hdr) + bytes(bat) + pad + bytes(body) + footer


def wrap_vhdx(data: bytes, block_size: int = 2 << 20,
              logical_sector: int = 512,
              physical_sector: int = 4096) -> bytes:
    """VHDX with one BAT entry per payload block and a real metadata region."""
    virtual_size = len(data) + (-len(data) % SECTOR)
    padded = bytes(data) + b"\x00" * (virtual_size - len(data))
    block_count = (virtual_size + block_size - 1) // block_size
    stored = padded + b"\x00" * (block_count * block_size - len(padded))

    bat_region_offset = 1 << 20
    metadata_region_offset = 2 << 20
    data_offset = 3 << 20

    total = data_offset + block_count * block_size
    out = bytearray(total)

    # File type identifier (64 KiB).
    out[0:8] = b"vhdxfile"
    out[8:8 + 2 * 12] = "vhdpeek".encode("utf-16-le")

    # Two image headers at 64 KiB and 128 KiB.
    for i in range(2):
        hoff = (64 << 10) + i * (64 << 10)
        out[hoff:hoff + 4] = b"head"
        struct.pack_into("<Q", out, hoff + 8, i + 1)
        struct.pack_into("<H", out, hoff + 66, 1)

    # Two region tables at 192 KiB and 256 KiB.
    bat_length = block_count * 8
    for i in range(2):
        toff = (192 << 10) + i * (64 << 10)
        out[toff:toff + 4] = b"regi"
        struct.pack_into("<I", out, toff + 8, 2)
        e0 = toff + 16
        out[e0:e0 + 16] = guid_bytes(GUID_BAT)
        struct.pack_into("<Q", out, e0 + 16, bat_region_offset)
        struct.pack_into("<I", out, e0 + 24, max(bat_length, 1 << 20))
        struct.pack_into("<I", out, e0 + 28, 1)
        e1 = toff + 48
        out[e1:e1 + 16] = guid_bytes(GUID_METADATA)
        struct.pack_into("<Q", out, e1 + 16, metadata_region_offset)
        struct.pack_into("<I", out, e1 + 24, 1 << 20)
        struct.pack_into("<I", out, e1 + 28, 1)

    # BAT: state FULLY_PRESENT, file offset in MiB.
    for i in range(block_count):
        file_offset = data_offset + i * block_size
        entry = ((file_offset >> 20) << 20) | 4
        struct.pack_into("<Q", out, bat_region_offset + i * 8, entry)

    # Metadata region.
    moff = metadata_region_offset
    out[moff:moff + 8] = b"metadata"
    items: List[Tuple[str, bytes]] = [
        (GUID_FILE_PARAMETERS,
         struct.pack("<II", block_size, 0)),
        (GUID_VIRTUAL_SIZE, struct.pack("<Q", virtual_size)),
        (GUID_LOGICAL_SECTOR, struct.pack("<I", logical_sector)),
        (GUID_PHYSICAL_SECTOR, struct.pack("<I", physical_sector)),
        (GUID_VIRTUAL_DISK_ID, uuid.uuid4().bytes_le),
    ]
    struct.pack_into("<H", out, moff + 10, len(items))
    item_offset = 64 << 10
    for i, (guid, payload) in enumerate(items):
        eoff = moff + 32 + i * 32
        out[eoff:eoff + 16] = guid_bytes(guid)
        struct.pack_into("<I", out, eoff + 16, item_offset)
        struct.pack_into("<I", out, eoff + 20, len(payload))
        struct.pack_into("<I", out, eoff + 24, 4)
        out[moff + item_offset:moff + item_offset + len(payload)] = payload
        item_offset += (len(payload) + 7) & ~7

    out[data_offset:data_offset + len(stored)] = stored
    return bytes(out)


# ---------------------------------------------------------------------------
# Disk assembly
# ---------------------------------------------------------------------------

def assemble_disk(fs_bytes: bytes, scheme: str = "mbr",
                  start_lba: int = 1,
                  total_sectors: Optional[int] = None,
                  gpt_type: str = "0FC63DAF-8483-4772-8E79-3D69D8477DE4",
                  mbr_type: int = 0x83,
                  gpt_name: str = "root") -> bytes:
    """Wrap filesystem bytes in a partition table."""
    fs_sectors = (len(fs_bytes) + SECTOR - 1) // SECTOR
    end_lba = start_lba + fs_sectors - 1
    if scheme == "gpt":
        disk_sectors = total_sectors or (end_lba + 34)
        table = build_gpt(disk_sectors, [(start_lba, end_lba, gpt_type, gpt_name)])
    else:
        disk_sectors = total_sectors or (end_lba + 1)
        table = build_mbr([(start_lba, fs_sectors, mbr_type, "fs")])
    disk = bytearray(disk_sectors * SECTOR)
    disk[:len(table)] = table
    disk[start_lba * SECTOR:start_lba * SECTOR + len(fs_bytes)] = fs_bytes
    return bytes(disk)


def wrap_sparse_vhd(blocks: Dict[int, bytes], virtual_size: int,
                    block_size: int = 2 << 20) -> bytes:
    """
    Dynamic VHD where only the supplied blocks are allocated.

    This models a real large image: `blocks` maps a container-block index to
    that block's contents, everything else stays a BAT hole that reads as
    zeros.  A 60 GiB virtual disk therefore needs only as much file space as
    the blocks that are actually present.
    """
    total_blocks = (virtual_size + block_size - 1) // block_size
    bitmap_size = 512

    header_offset = SECTOR
    bat_offset = header_offset + 1024
    bat_bytes = total_blocks * 4
    blocks_offset = bat_offset + bat_bytes
    blocks_offset += -blocks_offset % SECTOR

    bat = bytearray(b"\xFF" * bat_bytes)
    body = bytearray()
    for index in sorted(blocks):
        if index >= total_blocks:
            raise ValueError(f"block {index} beyond virtual size")
        payload = blocks[index]
        if len(payload) > block_size:
            raise ValueError(f"block {index} larger than block_size")
        file_offset = blocks_offset + len(body)
        struct.pack_into(">I", bat, index * 4, file_offset // SECTOR)
        body.extend(b"\xFF" * bitmap_size)
        body.extend(payload)
        body.extend(b"\x00" * (block_size - len(payload)))

    hdr = bytearray(1024)
    hdr[0:8] = b"cxsparse"
    struct.pack_into(">Q", hdr, 8, 0xFFFFFFFFFFFFFFFF)
    struct.pack_into(">Q", hdr, 16, bat_offset)
    struct.pack_into(">I", hdr, 24, 0x00010000)
    struct.pack_into(">I", hdr, 28, total_blocks)
    struct.pack_into(">I", hdr, 32, block_size)
    hdr[40:56] = b"\x00" * 16

    footer = _vhd_footer(3, virtual_size, header_offset)
    pad = b"\x00" * (blocks_offset - (bat_offset + bat_bytes))
    return footer + bytes(hdr) + bytes(bat) + pad + bytes(body) + footer


def assemble_disk_multi(partitions, scheme: str = "gpt",
                        total_sectors: Optional[int] = None) -> bytes:
    """
    Wrap several filesystems in one partition table.

    partitions: [(start_lba, fs_bytes, mbr_type, gpt_type, gpt_name), ...]
    """
    spans = []
    for start, fs_bytes, mbr_type, gpt_type, gpt_name in partitions:
        sectors = (len(fs_bytes) + SECTOR - 1) // SECTOR
        spans.append((start, start + sectors - 1, mbr_type, gpt_type, gpt_name))

    last = max(end for _, end, _, _, _ in spans)
    disk_sectors = total_sectors or (last + 34)
    if scheme == "gpt":
        table = build_gpt(disk_sectors,
                          [(start, end, gpt, name)
                           for start, end, _mbr, gpt, name in spans])
    else:
        table = build_mbr([(start, end - start + 1, mbr, name)
                           for start, end, mbr, _gpt, name in spans])

    disk = bytearray(disk_sectors * SECTOR)
    disk[:len(table)] = table
    for (start, _fs, _mbr, _gpt, _name), (_, _end, _, _, _) in zip(partitions, spans):
        offset = start * SECTOR
        disk[offset:offset + len(_fs)] = _fs
    return bytes(disk)
