"""
Partition types and the name tables used to label them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

MBR_EXTENDED_TYPES = (0x05, 0x0F, 0x85)
GPT_PROTECTIVE_TYPE = 0xEE

MBR_TYPE_NAMES = {
    0x00: "empty",
    0x01: "FAT12",
    0x04: "FAT16 <32M",
    0x05: "extended",
    0x06: "FAT16",
    0x07: "NTFS/exFAT/HPFS",
    0x0B: "FAT32 (CHS)",
    0x0C: "FAT32 (LBA)",
    0x0E: "FAT16 (LBA)",
    0x0F: "extended (LBA)",
    0x82: "Linux swap",
    0x83: "Linux",
    0x85: "Linux extended",
    0x8E: "Linux LVM",
    0xA5: "FreeBSD",
    0xA8: "macOS UFS",
    0xAB: "macOS boot",
    0xAF: "macOS HFS+",
    0xBE: "Solaris boot",
    0xEE: "GPT protective",
    0xEF: "EFI System",
    0xFD: "Linux RAID",
}

GPT_TYPE_GUIDS = {
    "C12A7328-F81F-11D2-BA4B-00A0C93EC93B": "EFI System",
    "21686148-6449-6E6F-744E-656564454649": "BIOS boot",
    "0FC63DAF-8483-4772-8E79-3D69D8477DE4": "Linux filesystem",
    "4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709": "Linux root (x86-64)",
    "BC13C2FF-59E6-4262-A352-B275FD6F7172": "Linux extended boot",
    "933AC7E1-2EB4-4F13-B844-0E14E2AEF915": "Linux /home",
    "A19D880F-05FC-4D3B-A006-743F0F84911E": "Linux RAID",
    "E6D6D379-F507-44C2-A23C-238F2A3DF928": "Linux LVM",
    "0657FD6D-A4AB-4C43-84A3-E4B2D3F0E4C3": "Linux swap",
    "EBD0A0A2-B2E5-4433-87C0-68B6B72699C7": "Microsoft basic data",
    "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC": "Windows recovery",
    "5808C8AA-7E8F-42E0-85D2-E1E90434CFB3": "Windows LDM metadata",
    "AF9B60A0-1431-4F62-BC68-3311714A69AD": "Windows LDM data",
    "48465300-0000-11AA-AA11-00306543ECAC": "Apple HFS+",
    "7C3457EF-0000-11AA-AA11-00306543ECAC": "Apple APFS",
    "2DC27766-F623-4200-9D64-115E9BFD4A08": "reserved",
}


@dataclass
class Partition:
    index: int
    start_lba: int
    end_lba: int
    type: str                      # "0x0C", or the GPT type name
    type_guid: Optional[str] = None
    name: Optional[str] = None
    sector_size: int = 512
    scheme: str = "mbr"            # mbr | gpt

    @property
    def size_bytes(self) -> int:
        return (self.end_lba - self.start_lba + 1) * self.sector_size

    @property
    def start_offset(self) -> int:
        return self.start_lba * self.sector_size

    def __repr__(self) -> str:
        label = f" ({self.name})" if self.name else ""
        return (f"Partition[{self.index}] start={self.start_lba} "
                f"end={self.end_lba} type={self.type}{label}")


def guid_string(raw: bytes) -> str:
    """Canonical string form of a 16-byte on-disk GUID (mixed-endian)."""
    d1, d2, d3 = struct.unpack_from("<IHH", raw, 0)
    return (f"{d1:08X}-{d2:04X}-{d3:04X}-"
            f"{raw[8]:02X}{raw[9]:02X}-{raw[10:16].hex().upper()}")


def decode_utf16le(raw: bytes) -> Optional[str]:
    text = raw.decode("utf-16-le", "replace").split("\x00", 1)[0].strip()
    return text or None
