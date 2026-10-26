"""Attribute lookup, runlist reads and $ATTRIBUTE_LIST merging."""

from __future__ import annotations

from typing import List, Optional

from .fixup import _parse_record
from .records import (
    ATTR_ATTRIBUTE_LIST,
    ATTR_DATA,
    MFT_REF_MASK,
    _Attr,
    _Record,
    _Run,
    _normalize_runs,
    _u16,
    _u32,
    _u64,
)


def _find_attr(
    attrs: List[_Attr], attr_type: int, name: str = ""
) -> Optional[_Attr]:
    for attr in attrs:
        if attr.type == attr_type and attr.name == name:
            return attr
    return None


def _find_any_attr(attrs: List[_Attr], attr_type: int) -> Optional[_Attr]:
    for attr in attrs:
        if attr.type == attr_type:
            return attr
    return None


def _data_attr(attrs: List[_Attr]) -> Optional[_Attr]:
    fragments = [
        attr for attr in attrs if attr.type == ATTR_DATA and not attr.name
    ]
    if not fragments:
        return None
    if len(fragments) == 1:
        return fragments[0]

    resident = next((attr for attr in fragments if attr.resident), None)
    if resident is not None:
        return resident

    runs: List[_Run] = []
    data_size = 0
    initialized_size = 0
    flags = 0
    compression_unit = 0
    for attr in fragments:
        runs.extend(attr.runs)
        data_size = max(data_size, attr.data_size)
        initialized_size = max(initialized_size, attr.initialized_size)
        flags |= attr.flags
        compression_unit = max(compression_unit, attr.compression_unit)
    return _Attr(
        type=ATTR_DATA,
        name="",
        flags=flags,
        resident=False,
        runs=_normalize_runs(runs),
        data_size=data_size,
        initialized_size=initialized_size,
        compression_unit=compression_unit,
    )


def _attr_list_entries(reader, attrs: List[_Attr]) -> List[tuple[int, str, int]]:
    """Return (type, name, base record) tuples from $ATTRIBUTE_LIST."""
    attr_list = _find_attr(attrs, ATTR_ATTRIBUTE_LIST)
    if attr_list is None:
        return []
    if attr_list.resident:
        data = attr_list.value
    else:
        data = _read_runs(
            reader,
            attr_list.runs,
            attr_list.data_size,
            0,
            attr_list.data_size,
            attr_list.initialized_size,
        )

    entries: List[tuple[int, str, int]] = []
    pos = 0
    while pos + 26 <= len(data):
        attr_type = _u32(data, pos)
        length = _u16(data, pos + 4)
        name_len = data[pos + 6]
        name_off = data[pos + 7]
        if length < 26 or pos + length > len(data):
            break
        ref = _u64(data, pos + 0x10) & MFT_REF_MASK
        name = ""
        name_start = pos + name_off
        if (
            name_len
            and name_off >= 26
            and name_start + name_len * 2 <= pos + length
        ):
            name = data[name_start:name_start + name_len * 2].decode(
                "utf-16-le", "replace"
            )
        entries.append((attr_type, name, ref))
        pos += length
    return entries


def _merge_extension_attrs(reader, record: _Record) -> List[_Attr]:
    """Append attributes stored in extension records named by $ATTRIBUTE_LIST."""
    pending = [
        entry[2]
        for entry in _attr_list_entries(reader, record.attrs)
        if entry[2] and entry[2] != record.number
    ]
    if not pending:
        return record.attrs

    attrs = list(record.attrs)
    seen = {record.number}
    while pending and len(seen) < 64:
        ref = pending.pop(0)
        if ref in seen:
            continue
        seen.add(ref)
        raw = _read_runs(
            reader,
            reader._mft_runs,
            reader._mft_size,
            ref * reader.mft_record_size,
            reader.mft_record_size,
        )
        ext = _parse_record(raw, ref)
        if ext is None:
            continue
        attrs.extend(ext.attrs)
        for entry in _attr_list_entries(reader, ext.attrs):
            if entry[2] and entry[2] not in seen:
                pending.append(entry[2])
    return attrs


def _read_runs(
    reader,
    runs: List[_Run],
    total_size: int,
    offset: int,
    size: Optional[int],
    initialized_size: Optional[int] = None,
) -> bytes:
    if offset < 0:
        offset = 0
    if total_size < 0:
        total_size = 0
    if size is None:
        size = total_size - offset
    if size <= 0 or offset >= total_size:
        return b""
    if size > total_size - offset:
        size = total_size - offset
    if initialized_size is None:
        initialized_size = total_size

    out = bytearray(size)
    end = offset + size
    cluster_size = reader.cluster_size
    for run in runs:
        run_start = run.vcn * cluster_size
        run_end = run_start + run.count * cluster_size
        if run_end <= offset:
            continue
        if run_start >= end:
            break
        low = max(offset, run_start)
        high = min(end, run_end)
        if run.lcn is None or low >= initialized_size:
            continue
        high = min(high, initialized_size)
        if high <= low:
            continue
        disk_offset = run.lcn * cluster_size + (low - run_start)
        count = high - low
        out[low - offset:low - offset + count] = reader.view.read(
            disk_offset, count
        )
    return bytes(out)
