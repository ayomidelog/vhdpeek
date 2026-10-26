"""Directory B-tree index parsing, path lookup and entry conversion."""

from __future__ import annotations

from typing import Dict, List, Optional

from ...core.volume import Entry
from .attributes import _find_any_attr, _find_attr, _read_runs
from .fixup import _fixup
from .mft import _record
from .records import (
    ATTR_INDEX_ALLOCATION,
    ATTR_INDEX_ROOT,
    FILE_NAME_DIRECTORY,
    FILE_RECORD_IS_DIR,
    INDEX_ENTRY_HAS_SUBNODE,
    INDEX_ENTRY_LAST,
    ROOT_MFT,
    _Attr,
    _IndexEntry,
    _Record,
    _Run,
    _filetime,
    _normalize_runs,
    _u16,
    _u32,
    _u64,
)


def _index_attr(attrs: List[_Attr], attr_type: int) -> Optional[_Attr]:
    fragments = [
        attr
        for attr in attrs
        if attr.type == attr_type and (not attr.name or attr.name == "$I30")
    ]
    if not fragments:
        return None
    if len(fragments) == 1:
        return fragments[0]
    if any(attr.resident for attr in fragments):
        return next(attr for attr in fragments if attr.resident)

    runs: List[_Run] = []
    data_size = 0
    initialized_size = 0
    for attr in fragments:
        runs.extend(attr.runs)
        data_size = max(data_size, attr.data_size)
        initialized_size = max(initialized_size, attr.initialized_size)
    return _Attr(
        type=attr_type,
        name="$I30",
        flags=0,
        resident=False,
        runs=_normalize_runs(runs),
        data_size=data_size,
        initialized_size=initialized_size,
    )


def _index_entries(reader, record: _Record) -> List[_IndexEntry]:
    root = _find_attr(record.attrs, ATTR_INDEX_ROOT, "$I30")
    if root is None:
        root = _find_any_attr(record.attrs, ATTR_INDEX_ROOT)
    if root is None or not root.resident or len(root.value) < 0x20:
        return []

    value = root.value
    record_size = _u32(value, 0x08) or reader.index_record_size
    if record_size < 512 or record_size % 512:
        record_size = reader.index_record_size

    header = 0x10
    entries_off = _u32(value, header)
    index_len = _u32(value, header + 4)
    start = header + entries_off
    end = header + index_len
    if start < header or end > len(value) or start > end:
        return []

    allocation = _index_attr(record.attrs, ATTR_INDEX_ALLOCATION)
    entries: List[_IndexEntry] = []
    visited: set[int] = set()
    _walk_entries(
        reader, value, start, end, entries, allocation, record_size, visited, 0
    )
    return entries


def _walk_entries(
    reader,
    buf: bytes,
    start: int,
    end: int,
    out: List[_IndexEntry],
    allocation: Optional[_Attr],
    record_size: int,
    visited: set[int],
    depth: int,
) -> None:
    pos = start
    while pos + 0x10 <= end:
        entry_len = _u16(buf, pos + 8)
        key_len = _u16(buf, pos + 0x0A)
        flags = _u16(buf, pos + 0x0C)
        if entry_len < 0x10 or pos + entry_len > end:
            break

        has_subnode = bool(flags & INDEX_ENTRY_HAS_SUBNODE)
        is_last = bool(flags & INDEX_ENTRY_LAST)

        if not is_last and key_len:
            key_off = pos + 0x10
            if key_off + key_len <= pos + entry_len:
                entry = _parse_index_key(buf, pos, key_off, key_len)
                if entry is not None:
                    out.append(entry)

        if has_subnode and entry_len >= 0x18 and depth < 64:
            child_vcn = _u64(buf, pos + entry_len - 8)
            if child_vcn not in visited:
                visited.add(child_vcn)
                _walk_index_buffer(
                    reader,
                    child_vcn,
                    out,
                    allocation,
                    record_size,
                    visited,
                    depth + 1,
                )

        if is_last:
            break
        pos += entry_len


def _walk_index_buffer(
    reader,
    vcn: int,
    out: List[_IndexEntry],
    allocation: Optional[_Attr],
    record_size: int,
    visited: set[int],
    depth: int,
) -> None:
    if allocation is None or allocation.resident:
        return
    offset = vcn * reader.cluster_size
    if offset >= allocation.data_size:
        return
    raw = _read_runs(
        reader,
        allocation.runs,
        allocation.data_size,
        offset,
        record_size,
        allocation.initialized_size,
    )
    if len(raw) < 0x20 or raw[:4] != b"INDX":
        return
    buf = _fixup(raw)
    if buf is None:
        return

    header = 0x18
    entries_off = _u32(buf, header)
    index_len = _u32(buf, header + 4)
    start = header + entries_off
    end = header + index_len
    if start < header or end > len(buf) or start > end:
        return
    _walk_entries(
        reader, buf, start, end, out, allocation, record_size, visited, depth
    )


def _parse_index_key(
    buf: bytes, entry_off: int, off: int, length: int
) -> Optional[_IndexEntry]:
    if length < 0x42:
        return None
    name_len = buf[off + 0x40]
    name_end = off + 0x42 + name_len * 2
    if name_end > off + length:
        return None
    name = buf[off + 0x42:name_end].decode("utf-16-le", "replace")
    file_flags = _u32(buf, off + 0x38)
    return _IndexEntry(
        ref=_u64(buf, entry_off),
        name=name,
        namespace=buf[off + 0x41],
        is_dir=bool(file_flags & FILE_NAME_DIRECTORY),
        size=_u64(buf, off + 0x30),
        mtime=_filetime(_u64(buf, off + 0x10)),
    )


def _collect_entries(reader, record: _Record) -> List[_IndexEntry]:
    raw = _index_entries(reader, record)

    grouped: Dict[int, List[_IndexEntry]] = {}
    for entry in raw:
        if not entry.name or entry.name in (".", ".."):
            continue
        grouped.setdefault(entry.mft, []).append(entry)

    entries: List[_IndexEntry] = []
    for group in grouped.values():
        chosen = [entry for entry in group if entry.namespace in (1, 3)]
        if not chosen:
            chosen = [entry for entry in group if entry.namespace == 0]
        if not chosen:
            chosen = group
        entries.extend(chosen)

    entries.sort(key=lambda entry: entry.name.casefold())
    return entries


def _lookup(
    reader, parts: tuple[str, ...]
) -> Optional[tuple[int, int, _IndexEntry]]:
    mft = ROOT_MFT
    sequence = 0
    entry: Optional[_IndexEntry] = None
    for part in parts:
        record = _record(reader, mft)
        if (
            record is None
            or not (record.flags & FILE_RECORD_IS_DIR)
            or (sequence and record.sequence != sequence)
        ):
            return None

        children = _collect_entries(reader, record)
        match = next((child for child in children if child.name == part), None)
        if match is None:
            folded = part.casefold()
            match = next(
                (
                    child
                    for child in children
                    if child.name.casefold() == folded
                ),
                None,
            )
        if match is None:
            return None
        mft, sequence, entry = match.mft, match.sequence, match

    if entry is None:
        return None
    return mft, sequence, entry


def _entry_from_index(entry: _IndexEntry, path: str) -> Entry:
    return Entry(
        name=entry.name,
        path=path,
        is_dir=entry.is_dir,
        size=0 if entry.is_dir else entry.size,
        mtime=entry.mtime,
        extra={"mft": entry.mft, "namespace": entry.namespace},
    )
