"""NTFS reader: boot sector, public API and volume metadata."""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable, List, Optional

from ...core.volume import ByteView, Entry, join_path, norm_path
from .attributes import _data_attr, _find_attr, _read_runs
from .compression import _read_compressed
from .index import _collect_entries, _entry_from_index, _lookup
from .mft import _init_mft, _record
from .records import (
    ATTR_FLAG_COMPRESSED,
    ATTR_VOLUME_NAME,
    FILE_RECORD_IS_DIR,
    ROOT_MFT,
    _Record,
    _Run,
    _i8,
    _u16,
    _u64,
)


class NtfsReader:
    """Read-only NTFS reader over a `ByteView` covering one partition."""

    fs_type = "ntfs"

    def __init__(self, view: ByteView):
        self.view = view

        boot = view.read(0, 512)
        if len(boot) < 512 or boot[3:11] != b"NTFS    ":
            raise ValueError("not an NTFS volume (missing NTFS OEM identifier)")

        bps = _u16(boot, 0x0B) or int(getattr(view, "sector_size", 512))
        if bps not in (512, 1024, 2048, 4096):
            raise ValueError(f"unsupported NTFS bytes per sector: {bps}")
        spc = boot[0x0D]
        if spc == 0 or spc & (spc - 1):
            raise ValueError(f"invalid NTFS sectors per cluster: {spc}")

        self.bytes_per_sector = bps
        self.sectors_per_cluster = spc
        self.cluster_size = bps * spc

        total_sectors = _u64(boot, 0x28)
        if total_sectors == 0:
            total_sectors = view.size // bps
        self.total_sectors = total_sectors
        self.total_clusters = total_sectors // spc
        if self.total_clusters <= 0:
            raise ValueError("NTFS volume has no clusters")

        self.mft_lcn = _u64(boot, 0x30)
        self.mftmirr_lcn = _u64(boot, 0x38)
        self.serial = _u64(boot, 0x48)

        default_record = 1024
        self.mft_record_size = self._size_field(
            _i8(boot, 0x40), self.cluster_size, default_record
        )
        default_index = 4096
        self.index_record_size = self._size_field(
            _i8(boot, 0x44), self.cluster_size, default_index
        )

        self._record_cache: OrderedDict[int, Optional[_Record]] = OrderedDict()
        self._record_cache_limit = 512
        self._loading: set[int] = set()
        self._mft_runs: List[_Run] = []
        self._mft_size = 0

        _init_mft(self)
        self.label = self._read_label()

    # ------------------------------------------------------------------
    # Boot / $MFT bootstrap
    # ------------------------------------------------------------------

    @staticmethod
    def _size_field(value: int, cluster_size: int, default: int) -> int:
        """Decode the signed 'clusters per record' encoding of the boot sector."""
        if value < 0:
            size = 1 << (-value)
        elif value > 0:
            size = value * cluster_size
        else:
            return default
        if size < 512 or size % 512 or size > (1 << 20):
            return default
        return size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_dir(self, path: str = "") -> List[Entry]:
        parts = norm_path(path)
        if parts:
            resolved = _lookup(self, parts)
            if resolved is None:
                raise FileNotFoundError(path)
            mft, sequence, _entry = resolved
            record = _record(self, mft)
            if (
                record is None
                or (sequence and record.sequence != sequence)
                or not (record.flags & FILE_RECORD_IS_DIR)
            ):
                raise FileNotFoundError(path)
            prefix = "/" + "/".join(parts)
        else:
            record = _record(self, ROOT_MFT)
            if record is None or not (record.flags & FILE_RECORD_IS_DIR):
                raise FileNotFoundError(path)
            prefix = ""

        return [
            _entry_from_index(entry, join_path(prefix, entry.name))
            for entry in _collect_entries(self, record)
        ]

    def stat(self, path: str) -> Optional[Entry]:
        parts = norm_path(path)
        if not parts:
            record = _record(self, ROOT_MFT)
            if record is None or not (record.flags & FILE_RECORD_IS_DIR):
                return None
            return Entry(
                name="",
                path="",
                is_dir=True,
                size=0,
                mtime=None,
                extra={"mft": ROOT_MFT},
            )

        resolved = _lookup(self, parts)
        if resolved is None:
            return None
        mft, sequence, entry = resolved
        record = _record(self, mft)
        if record is None or (sequence and record.sequence != sequence):
            return None
        return _entry_from_index(entry, "/" + "/".join(parts))

    def read_file(
        self, path: str, offset: int = 0, size: Optional[int] = None
    ) -> bytes:
        parts = norm_path(path)
        if not parts:
            return b""
        resolved = _lookup(self, parts)
        if resolved is None:
            return b""
        mft, sequence, _entry = resolved
        record = _record(self, mft)
        if (
            record is None
            or (sequence and record.sequence != sequence)
            or (record.flags & FILE_RECORD_IS_DIR)
        ):
            return b""

        data = _data_attr(record.attrs)
        if data is None:
            return b""

        if data.resident:
            value = data.value
            if offset < 0:
                offset = 0
            if size is None:
                size = len(value) - offset
            if size <= 0 or offset >= len(value):
                return b""
            return value[offset:offset + size]

        if data.flags & ATTR_FLAG_COMPRESSED and data.compression_unit:
            return _read_compressed(self, data, offset, size)
        return _read_runs(
            self,
            data.runs,
            data.data_size,
            offset,
            size,
            data.initialized_size,
        )

    def file_reader(self, path: str) -> Callable[[int, int], bytes]:
        parts = norm_path(path)
        if not parts:
            return _empty_reader
        resolved = _lookup(self, parts)
        if resolved is None:
            return _empty_reader
        mft, sequence, _entry = resolved
        record = _record(self, mft)
        if (
            record is None
            or (sequence and record.sequence != sequence)
            or (record.flags & FILE_RECORD_IS_DIR)
        ):
            return _empty_reader

        data = _data_attr(record.attrs)
        if data is None:
            return _empty_reader

        if data.resident:
            value = data.value

            def read_resident(offset: int, size: Optional[int]) -> bytes:
                if offset < 0:
                    offset = 0
                if size is None:
                    size = len(value) - offset
                if size <= 0 or offset >= len(value):
                    return b""
                return value[offset:offset + size]

            return read_resident

        if data.flags & ATTR_FLAG_COMPRESSED and data.compression_unit:

            def read_compressed(offset: int, size: Optional[int]) -> bytes:
                return _read_compressed(self, data, offset, size)

            return read_compressed

        runs = data.runs
        total_size = data.data_size
        initialized_size = data.initialized_size

        def read_non_resident(offset: int, size: Optional[int]) -> bytes:
            return _read_runs(
                self, runs, total_size, offset, size, initialized_size
            )

        return read_non_resident

    # ------------------------------------------------------------------
    # Volume metadata
    # ------------------------------------------------------------------

    def _read_label(self) -> str:
        record = _record(self, 3)
        if record is None:
            return ""
        attr = _find_attr(record.attrs, ATTR_VOLUME_NAME)
        if attr is None or not attr.resident:
            return ""
        return attr.value.decode("utf-16-le", "replace").rstrip("\x00")


def _empty_reader(offset: int, size: int) -> bytes:
    return b""
