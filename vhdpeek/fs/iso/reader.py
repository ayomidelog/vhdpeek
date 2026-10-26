"""The ISO 9660 reader itself."""

from __future__ import annotations

import struct
from typing import Callable, Dict, List, Optional, Tuple

from ...core.volume import ByteView, Entry, join_path, norm_path

from .descriptors import (_DESCRIPTOR_SIZE, _ROOT_RECORD_OFFSET,
                          _DescriptorMixin)
from .directory import _DirectoryMixin
from .records import _Record
from .rockridge import _RockRidgeMixin


class IsoReader(_DescriptorMixin, _RockRidgeMixin, _DirectoryMixin):
    """
    Read-only view of an ISO 9660 image through a :class:`ByteView`.

    The reader prefers Rock Ridge names when the chosen tree carries SUSP
    metadata, otherwise it uses the Joliet supplementary descriptor when one
    is present, and finally falls back to plain 8.3 ISO names.
    """

    fs_type = "iso9660"

    def __init__(self, view: ByteView):
        self._view = view
        self._susp_skip = 0
        self._has_rr = False
        self._joliet = False
        self._joliet_vd: Optional[bytes] = None
        self._dir_cache: Dict[Tuple[str, ...], List[_Record]] = {}

        pvd, joliet = self._read_descriptors()
        self._volume_blocks = struct.unpack_from("<I", pvd, 80)[0]
        block_size = struct.unpack_from("<H", pvd, 128)[0]
        if block_size not in (512, 1024, 2048, 4096):
            block_size = _DESCRIPTOR_SIZE
        self._block_size = block_size
        self._volume_size = self._volume_blocks * block_size
        volume_id = pvd[40:72].decode("latin-1").rstrip("\x00 ").strip()
        if not volume_id and joliet is not None:
            volume_id = joliet[40:72].decode(
                "utf-16-be", "replace").rstrip("\x00 ").strip()
        self._volume_id = volume_id

        root_raw = pvd[_ROOT_RECORD_OFFSET:_ROOT_RECORD_OFFSET + 34]
        root = self._parse_record(root_raw, joliet=False)
        if root is None:
            raise ValueError("ISO 9660 primary volume descriptor has no root")
        self._has_rr = self._detect_susp(root)
        if not self._has_rr and joliet is not None:
            joliet_raw = joliet[_ROOT_RECORD_OFFSET:_ROOT_RECORD_OFFSET + 34]
            joliet_root = self._parse_record(joliet_raw, joliet=True)
            if joliet_root is not None:
                root = joliet_root
                self._joliet = True
                self._has_rr = self._detect_susp(root)
        self._root = root

    # ------------------------------------------------------------------
    # Volume information
    # ------------------------------------------------------------------

    @property
    def volume_id(self) -> str:
        return self._volume_id

    @property
    def label(self) -> str:
        return self._volume_id

    @property
    def volume_size(self) -> int:
        """Size of the volume in bytes (volume space size * block size)."""
        return self._volume_size

    @property
    def volume_blocks(self) -> int:
        return self._volume_blocks

    @property
    def block_size(self) -> int:
        return self._block_size

    @property
    def has_joliet(self) -> bool:
        """True when a Joliet supplementary descriptor is present."""
        return self._joliet_vd is not None

    @property
    def has_rock_ridge(self) -> bool:
        return self._has_rr

    @property
    def root_extent(self) -> int:
        return self._root.extents[0].offset // self._block_size

    # ------------------------------------------------------------------
    # Public filesystem API
    # ------------------------------------------------------------------

    def list_dir(self, path: str = "") -> List[Entry]:
        parts = norm_path(path)
        record, canonical = self._lookup(parts)
        if record is None:
            raise FileNotFoundError(path)
        if not record.is_dir:
            raise NotADirectoryError(path)
        entries: List[Entry] = []
        for child in self._directory_records(record, parts):
            if child.name in (".", "..") or child.relocated:
                continue
            entries.append(Entry(name=child.name,
                                 path=join_path(canonical, child.name),
                                 is_dir=child.is_dir,
                                 size=child.size,
                                 mtime=child.mtime))
        return entries

    def stat(self, path: str) -> Optional[Entry]:
        parts = norm_path(path)
        record, canonical = self._lookup(parts)
        if record is None:
            return None
        return Entry(name=record.name if parts else "",
                     path=canonical,
                     is_dir=record.is_dir,
                     size=record.size,
                     mtime=record.mtime)

    def read_file(self, path: str, offset: int = 0,
                  size: Optional[int] = None) -> bytes:
        if offset < 0:
            raise ValueError("negative offset")
        record, _ = self._lookup(norm_path(path))
        if record is None or record.is_dir:
            return b""
        total = record.size
        if offset >= total:
            return b""
        if size is None:
            size = total - offset
        if size <= 0:
            return b""
        size = min(size, total - offset)
        return self._read_record_range(record, offset, size)

    def file_reader(self, path: str) -> Callable[[int, int], bytes]:
        record, _ = self._lookup(norm_path(path))
        if record is None:
            raise FileNotFoundError(path)
        if record.is_dir:
            raise IsADirectoryError(path)
        total = record.size

        def reader(offset: int, size: int) -> bytes:
            if offset < 0:
                raise ValueError("negative offset")
            if size <= 0:
                return b""
            if offset >= total:
                return b"\x00" * size
            take = min(size, total - offset)
            data = self._read_record_range(record, offset, take)
            if len(data) < size:
                data += b"\x00" * (size - len(data))
            return data

        return reader
