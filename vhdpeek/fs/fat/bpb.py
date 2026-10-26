"""
FAT12 / FAT16 / FAT32 BPB parsing.

A FAT volume is laid out, relative to the start of the partition, as:

    offset 0
    | boot sector / BPB          |  bytes_per_sector bytes
    (reserved_sectors) * bps
    | FAT #0 ... FAT #(n-1)      |  fat_size_sectors * bps each
    (reserved_sectors + num_fats * fat_size_sectors) * bps
    | root directory (FAT12/16)  |  root_dir_sectors * bps
    data_start_sector * bps
    | cluster 2, cluster 3, ...  |  cluster_size = spc * bps each

BPB fields used here (offsets inside the boot sector):

    0x0B u16   bytes per sector
    0x0D u8    sectors per cluster
    0x0E u16   reserved sectors
    0x10 u8    number of FATs
    0x11 u16   root entry count (FAT12/16)
    0x13 u16   total sectors (16 bit)
    0x15 u8    media descriptor
    0x16 u16   FAT size in sectors (FAT12/16)
    0x20 u32   total sectors (when 0x13 is zero)
    0x24 u32   FAT size in sectors (FAT32)
    0x2B [11]  volume label (FAT12/16)
    0x2C u32   root directory cluster (FAT32)
    0x47 [11]  volume label (FAT32)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

from ...core.volume import ByteView
from .names import _clean_label

#: FAT type thresholds from the Microsoft specification (cluster counts).
_FAT12_MAX_CLUSTERS = 4085
_FAT16_MAX_CLUSTERS = 65525

def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]

def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]

@dataclass(frozen=True)
class Bpb:
    """The decoded, validated fields of a FAT boot sector."""

    bytes_per_sector: int
    sectors_per_cluster: int
    reserved_sectors: int
    num_fats: int
    root_entry_count: int
    media: int
    fat_size_sectors: int
    root_dir_sectors: int
    data_start_sector: int
    total_sectors: int
    cluster_count: int
    fat_type: str
    fs_type: str
    entry_bits: int
    eoc_min: int
    bad_cluster: int
    total_clusters: int
    max_cluster: int
    root_cluster: Optional[int]
    label: Optional[str]
    cluster_size: int
    fat_offset: int
    root_dir_offset: int
    data_offset: int

def parse(view: ByteView) -> Bpb:
    """Decode and validate the boot sector at the start of `view`."""
    boot = view.read(0, 512)
    if boot[3:11] == b"EXFAT   ":
        raise ValueError("exFAT is not supported")

    bytes_per_sector = _u16(boot, 0x0B)
    if bytes_per_sector not in (512, 1024, 2048, 4096):
        raise ValueError(
            f"not a FAT volume: bytes-per-sector {bytes_per_sector}"
        )

    sectors_per_cluster = boot[0x0D]
    if sectors_per_cluster == 0 or (
        sectors_per_cluster & (sectors_per_cluster - 1)
    ):
        raise ValueError(
            f"invalid FAT sectors-per-cluster {sectors_per_cluster}"
        )

    reserved_sectors = _u16(boot, 0x0E)
    num_fats = boot[0x10]
    root_entry_count = _u16(boot, 0x11)
    media = boot[0x15]

    fat_size16 = _u16(boot, 0x16)
    fat_size32 = _u32(boot, 0x24)
    fat_size = fat_size16 or fat_size32
    total_sectors = _u16(boot, 0x13) or _u32(boot, 0x20)

    if not (reserved_sectors and num_fats and fat_size and total_sectors):
        raise ValueError("not a FAT volume: zeroed BPB fields")

    root_dir_sectors = (
        root_entry_count * 32 + bytes_per_sector - 1
    ) // bytes_per_sector
    data_start_sector = (
        reserved_sectors
        + num_fats * fat_size
        + root_dir_sectors
    )
    if data_start_sector >= total_sectors:
        raise ValueError("not a FAT volume: data region starts past the end")

    # FAT32 is marked explicitly by a zero 16-bit FAT size with a populated
    # 32-bit one; mkfs.vfat -F 32 writes that even for volumes below the
    # 65525-cluster threshold.  Otherwise the cluster count decides.
    cluster_count = (
        total_sectors - data_start_sector
    ) // sectors_per_cluster
    forced_fat32 = fat_size16 == 0 and fat_size32 != 0
    if forced_fat32 or cluster_count >= _FAT16_MAX_CLUSTERS:
        fat_type = "FAT32"
        fs_type = "fat32"
        entry_bits = 32
        eoc_min = 0x0FFFFFF8
        bad_cluster = 0x0FFFFFF7
    elif cluster_count < _FAT12_MAX_CLUSTERS:
        fat_type = "FAT12"
        fs_type = "fat12"
        entry_bits = 12
        eoc_min = 0xFF8
        bad_cluster = 0xFF7
    else:
        fat_type = "FAT16"
        fs_type = "fat16"
        entry_bits = 16
        eoc_min = 0xFFF8
        bad_cluster = 0xFFF7

    # Never walk past what the FAT can address.
    fat_capacity = fat_size * bytes_per_sector * 8 // entry_bits
    total_clusters = min(cluster_count, fat_capacity)
    max_cluster = total_clusters + 2

    if fat_type == "FAT32":
        root = _u32(boot, 0x2C)
        root_cluster: Optional[int] = (
            root if 2 <= root < max_cluster else 2
        )
        label_raw = boot[0x47:0x52]
    else:
        root_cluster = None
        label_raw = boot[0x2B:0x36]
    label = _clean_label(label_raw)

    cluster_size = sectors_per_cluster * bytes_per_sector
    fat_offset = reserved_sectors * bytes_per_sector
    root_dir_offset = (
        reserved_sectors + num_fats * fat_size
    ) * bytes_per_sector
    data_offset = data_start_sector * bytes_per_sector

    return Bpb(
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        reserved_sectors=reserved_sectors,
        num_fats=num_fats,
        root_entry_count=root_entry_count,
        media=media,
        fat_size_sectors=fat_size,
        root_dir_sectors=root_dir_sectors,
        data_start_sector=data_start_sector,
        total_sectors=total_sectors,
        cluster_count=cluster_count,
        fat_type=fat_type,
        fs_type=fs_type,
        entry_bits=entry_bits,
        eoc_min=eoc_min,
        bad_cluster=bad_cluster,
        total_clusters=total_clusters,
        max_cluster=max_cluster,
        root_cluster=root_cluster,
        label=label,
        cluster_size=cluster_size,
        fat_offset=fat_offset,
        root_dir_offset=root_dir_offset,
        data_offset=data_offset,
    )
