"""Directory traversal and extent reads."""

from __future__ import annotations

from typing import List, Optional, Tuple

from ...core.volume import join_path
from .records import _MULTI_EXTENT, _Record


class _DirectoryMixin:
    def _read_extents(self, record: _Record) -> bytes:
        return b"".join(self._view.read(extent.offset, extent.size)
                        for extent in record.extents)

    def _parse_directory_data(self, data: bytes) -> List[_Record]:
        records: List[_Record] = []
        pos = 0
        total = len(data)
        while pos + 34 <= total:
            length = data[pos]
            if length == 0:
                pos = ((pos // self._block_size) + 1) * self._block_size
                continue
            if length < 34 or pos + length > total:
                pos = ((pos // self._block_size) + 1) * self._block_size
                continue
            record = self._parse_record(data[pos:pos + length], self._joliet)
            pos += length
            if record is not None:
                records.append(record)
        return records

    def _merge_multi_extent(self, records: List[_Record]) -> List[_Record]:
        merged: List[_Record] = []
        pending: Optional[_Record] = None
        for record in records:
            if pending is not None:
                if record.identifier == pending.identifier:
                    pending.extents.extend(record.extents)
                    pending.flags = record.flags
                    if not (record.flags & _MULTI_EXTENT):
                        merged.append(pending)
                        pending = None
                    continue
                merged.append(pending)
                pending = None
            if record.flags & _MULTI_EXTENT:
                pending = record
            else:
                merged.append(record)
        if pending is not None:
            merged.append(pending)
        return merged

    def _directory_records(self, record: _Record,
                           path: Tuple[str, ...]) -> List[_Record]:
        cached = self._dir_cache.get(path)
        if cached is not None:
            return cached
        data = self._read_extents(record)
        records = self._merge_multi_extent(self._parse_directory_data(data))
        self._dir_cache[path] = records
        return records

    def _lookup(self, parts: Tuple[str, ...]) -> Tuple[Optional[_Record], str]:
        record = self._root
        canonical = ""
        for index, part in enumerate(parts):
            if not record.is_dir:
                return None, canonical
            children = self._directory_records(record, parts[:index])
            match = None
            for child in children:
                if child.name == part:
                    match = child
                    break
            if match is None:
                return None, canonical
            record = match
            canonical = join_path(canonical, match.name)
        return record, canonical

    def _read_record_range(self, record: _Record, offset: int,
                           size: int) -> bytes:
        chunks: List[bytes] = []
        position = offset
        remaining = size
        for extent in record.extents:
            if remaining <= 0:
                break
            if position >= extent.size:
                position -= extent.size
                continue
            take = min(remaining, extent.size - position)
            chunks.append(self._view.read(extent.offset + position, take))
            remaining -= take
            position = 0
        return b"".join(chunks)
