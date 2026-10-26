"""FAT12/16/32 reader built on the BPB, table and directory modules."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ...core.volume import ByteView, Entry, norm_path
from . import bpb
from .directory import _DIR_ATTR, _parse_dir
from .table import FatTable, _chain_runs

class FatReader:
    """FAT12/16/32 volume accessed through a `ByteView`."""

    fs_type: str          # "fat12" / "fat16" / "fat32", decided in __init__

    def __init__(self, view: ByteView):
        self.view = view
        info = bpb.parse(view)

        self.bytes_per_sector = info.bytes_per_sector
        self.sectors_per_cluster = info.sectors_per_cluster
        self.reserved_sectors = info.reserved_sectors
        self.num_fats = info.num_fats
        self.root_entry_count = info.root_entry_count
        self.media = info.media
        self.fat_size_sectors = info.fat_size_sectors
        self.root_dir_sectors = info.root_dir_sectors
        self.data_start_sector = info.data_start_sector
        self.total_sectors = info.total_sectors
        self.fat_type = info.fat_type
        self.fs_type = info.fs_type
        self.root_cluster = info.root_cluster
        self.total_clusters = info.total_clusters
        self.cluster_size = info.cluster_size
        self._label = info.label
        self._fat_offset = info.fat_offset
        self._root_dir_offset = info.root_dir_offset
        self._data_offset = info.data_offset
        self._entry_bits = info.entry_bits
        self._eoc_min = info.eoc_min
        self._bad_cluster = info.bad_cluster
        self._max_cluster = info.max_cluster

        # Underscore aliases for callers that read the parsed BPB directly.
        self._bytes_per_sector = info.bytes_per_sector
        self._sectors_per_cluster = info.sectors_per_cluster
        self._cluster_count = info.cluster_count
        self._fat_type = info.fat_type
        self._root_dir_sector = (
            info.reserved_sectors + info.num_fats * info.fat_size_sectors
        )
        self._root_entries = info.root_entry_count
        self._total_clusters = info.total_clusters
        self._data_start = info.data_start_sector
        self._cluster_size = info.cluster_size
        self._root_dir_cluster = info.root_cluster

        self._table = FatTable(
            view,
            info.fat_offset,
            info.bytes_per_sector,
            info.entry_bits,
            info.eoc_min,
            info.bad_cluster,
            info.max_cluster,
            info.total_clusters,
        )
        self._dir_cache: Dict[Optional[int], List[Entry]] = {}

    # ------------------------------------------------------------------
    # Cluster / directory data
    # ------------------------------------------------------------------

    def _cluster_offset(self, cluster: int) -> int:
        return self._data_offset + (cluster - 2) * self.cluster_size

    def _read_clusters(self, first: int, count: int) -> bytes:
        return self.view.read(self._cluster_offset(first), count * self.cluster_size)

    def _dir_bytes(self, first_cluster: Optional[int]) -> bytes:
        """Raw directory contents.  `None` is the fixed FAT12/16 root region."""
        if first_cluster is None:
            return self.view.read(
                self._root_dir_offset,
                self.root_dir_sectors * self.bytes_per_sector,
            )
        if first_cluster < 2:
            return b""
        return b"".join(self._read_clusters(first, count)
                        for first, count in _chain_runs(
                            self._table._unique_chain(first_cluster)))

    # ------------------------------------------------------------------
    # Directory entries
    # ------------------------------------------------------------------

    def _entries(self, first_cluster: Optional[int],
                 prefix: str) -> List[Entry]:
        cached = self._dir_cache.get(first_cluster)
        if cached is None:
            cached, self._label = _parse_dir(
                self._dir_bytes(first_cluster),
                prefix,
                self._label,
                self.fat_type,
            )
            self._dir_cache[first_cluster] = cached
        return cached

    def _root_entry(self) -> Entry:
        return Entry(
            name="",
            path="",
            is_dir=True,
            extra={
                "first_cluster": self.root_cluster or 0,
                "attributes": _DIR_ATTR,
            },
        )

    def _entries_of(self, entry: Entry) -> List[Entry]:
        if entry.path == "":
            return self._entries(self.root_cluster, "")
        return self._entries(entry.extra["first_cluster"], entry.path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def label(self) -> Optional[str]:
        """Volume label: the BPB copy, falling back to the root-directory entry."""
        if self._label is None:
            self._entries(self.root_cluster, "")
        return self._label

    def list_dir(self, path: str = "") -> List[Entry]:
        parts = norm_path(path)
        if not parts:
            return list(self._entries(self.root_cluster, ""))
        entry = self.stat(path)
        if entry is None:
            raise FileNotFoundError(path)
        if not entry.is_dir:
            raise NotADirectoryError(path)
        return list(self._entries_of(entry))

    def stat(self, path: str) -> Optional[Entry]:
        parts = norm_path(path)
        current = self._root_entry()
        for part in parts:
            if not current.is_dir:
                return None
            folded = part.casefold()
            match = None
            for candidate in self._entries_of(current):
                if candidate.name.casefold() == folded:
                    match = candidate
                    break
            if match is None:
                return None
            current = match
        return current

    def _read_chain_range(self, first_cluster: int, offset: int,
                          count: int) -> bytes:
        """Read `count` bytes at `offset` from a cluster chain."""
        if first_cluster < 2 or count <= 0:
            return b""
        cluster_size = self.cluster_size
        first_index = offset // cluster_size
        last_index = (offset + count - 1) // cluster_size
        needed = last_index - first_index + 1

        out = bytearray()
        run_start = prev = -1
        run_count = 0
        seen = 0
        for cluster in self._table._chain(first_cluster, first_index):
            if run_start < 0:
                run_start = prev = cluster
                run_count = 1
            elif cluster == prev + 1:
                prev = cluster
                run_count += 1
            else:
                out += self._read_clusters(run_start, run_count)
                run_start = prev = cluster
                run_count = 1
            seen += 1
            if seen == needed:
                break
        if run_start >= 0:
            out += self._read_clusters(run_start, run_count)

        skip = offset - first_index * cluster_size
        return bytes(out[skip:skip + count])

    def _read_entry(self, entry: Entry, offset: int,
                    size: Optional[int]) -> bytes:
        total = entry.size
        if offset >= total:
            return b""
        count = total - offset if size is None else min(size, total - offset)
        if count <= 0:
            return b""
        return self._read_chain_range(entry.extra["first_cluster"], offset, count)

    def read_file(self, path: str, offset: int = 0,
                  size: Optional[int] = None) -> bytes:
        if offset < 0:
            raise ValueError("negative offset")
        entry = self.stat(path)
        if entry is None or entry.is_dir:
            return b""
        return self._read_entry(entry, offset, size)

    def file_reader(self, path: str) -> Callable[[int, int], bytes]:
        """A `(offset, size) -> bytes` reader for this file, for nesting."""
        entry = self.stat(path)
        if entry is None:
            raise FileNotFoundError(path)
        if entry.is_dir:
            raise IsADirectoryError(path)
        total = entry.size
        first_cluster = entry.extra["first_cluster"]

        def read(offset: int, size: int) -> bytes:
            if offset < 0:
                raise ValueError("negative offset")
            if size <= 0:
                return b""
            if offset >= total:
                return b"\x00" * size
            data = self._read_chain_range(
                first_cluster, offset, min(size, total - offset)
            )
            if len(data) < size:
                data += b"\x00" * (size - len(data))
            return data

        return read
