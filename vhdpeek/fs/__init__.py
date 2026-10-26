"""
Filesystem detection and mounting.

A filesystem reader is handed a byte window (`ByteView`) and exposes the
uniform path API from `core.volume`. This module is the only place that
knows which reader corresponds to which on-disk signature, so callers never
import a specific reader just to try it.
"""

from __future__ import annotations

from typing import Optional

from ..core.volume import ByteView, ReaderView
from .ext4 import Ext4Reader
from .fat import FatReader
from .iso import IsoReader
from .ntfs import NtfsReader

__all__ = [
    "FatReader",
    "NtfsReader",
    "Ext4Reader",
    "IsoReader",
    "probe",
    "open_reader",
    "mount_iso",
    "looks_like_iso",
]

#: Filesystem kinds a reader exists for.
KINDS = ("ntfs", "fat12", "fat16", "fat32", "ext", "iso")

_BY_KIND = {
    "ntfs": NtfsReader,
    "fat": FatReader,
    "fat12": FatReader,
    "fat16": FatReader,
    "fat32": FatReader,
    "ext": Ext4Reader,
    "iso": IsoReader,
}


def probe(view: ByteView) -> str:
    """
    Identify the filesystem from its signature bytes.

    NTFS and FAT both carry a 0x55AA boot signature, so the OEM id is checked
    first; ext4 keeps its magic 1024 bytes into the partition, not in the boot
    sector; ISO 9660 announces itself with a volume descriptor at sector 16.
    """
    head = view.read(0, 4096)
    if head[3:11] == b"NTFS    ":
        return "ntfs"
    if head[0:6] == b"\x01CD001":
        return "iso"
    if view.size > 16 * 2048 and view.read(16 * 2048, 6) == b"\x01CD001":
        return "iso"

    bytes_per_sector = int.from_bytes(head[0x0B:0x0D], "little")
    sectors_per_cluster = head[0x0D]
    if (head[510:512] == b"\x55\xAA"
            and bytes_per_sector in (512, 1024, 2048, 4096)
            and sectors_per_cluster in (1, 2, 4, 8, 16, 32, 64, 128)):
        if int.from_bytes(head[0x16:0x18], "little") == 0 \
                and int.from_bytes(head[0x24:0x28], "little") != 0:
            return "fat32"
        total_sectors = int.from_bytes(head[0x13:0x15], "little") or \
            int.from_bytes(head[0x20:0x24], "little")
        cluster_size = bytes_per_sector * sectors_per_cluster
        clusters = total_sectors * bytes_per_sector // cluster_size
        return "fat12" if clusters < 4085 else "fat16"

    if view.read(1024 + 0x38, 2) == b"\x53\xEF":
        return "ext"

    return "unknown"


def open_reader(view: ByteView, kind: Optional[str] = None):
    """
    Mount the filesystem in `view`, or raise ValueError if unrecognised.

    `kind` skips detection when the caller already knows (or overrides) it.
    """
    kind = kind or probe(view)
    reader_class = _BY_KIND.get(kind)
    if reader_class is None:
        raise ValueError(f"unsupported filesystem ({kind})")
    return reader_class(view)


def mount_iso(reader, path: str) -> IsoReader:
    """Mount an ISO stored inside a filesystem, unextracted."""
    entry = reader.stat(path)
    if entry is None:
        raise FileNotFoundError(f"{path}: not found in the filesystem")
    if entry.is_dir:
        raise IsADirectoryError(f"{path}: is a directory")
    return IsoReader(ReaderView(reader.file_reader(path), entry.size))


def looks_like_iso(path: str) -> bool:
    return path.lower().endswith(".iso")
