"""$MFT bootstrap, run expansion and cached record access."""

from __future__ import annotations

from typing import List, Optional

from .attributes import (
    _attr_list_entries,
    _find_attr,
    _merge_extension_attrs,
    _read_runs,
)
from .fixup import _parse_record
from .records import (
    ATTR_DATA,
    FILE_RECORD_IN_USE,
    MFT_REF_MASK,
    _MISSING,
    _Record,
    _Run,
    _normalize_runs,
)


def _init_mft(reader) -> None:
    if reader.mft_lcn >= reader.total_clusters:
        raise ValueError("$MFT lies outside the volume")

    raw = reader.view.read(
        reader.mft_lcn * reader.cluster_size, reader.mft_record_size
    )
    record = _parse_record(raw, 0)
    if record is None:
        raise ValueError("cannot parse $MFT record 0")

    data = _find_attr(record.attrs, ATTR_DATA, "")
    if data is None or data.resident:
        raise ValueError("$MFT has no non-resident unnamed $DATA attribute")

    runs = list(data.runs)
    size = data.data_size or data.initialized_size
    if not runs or size <= 0:
        raise ValueError("$MFT data runs are empty")

    runs, size = _expand_mft_runs(reader, record, runs, size)
    reader._mft_runs = _normalize_runs(runs)
    reader._mft_size = size


def _expand_mft_runs(
    reader, record: _Record, runs: List[_Run], size: int
) -> tuple[List[_Run], int]:
    """
    Merge $MFT $DATA fragments named by $ATTRIBUTE_LIST.

    The base record's runlist usually covers the extension records that
    hold the remaining fragments; when it does not, the fragment is
    retried after the runlist has grown.
    """
    pending = [
        entry
        for entry in _attr_list_entries(reader, record.attrs)
        if entry[0] == ATTR_DATA and not entry[1]
    ]
    seen = {0}
    for _ in range(64):
        if not pending:
            break
        retry = []
        progress = False
        for _type, _name, ref in pending:
            if ref in seen:
                continue
            raw = _read_runs(
                reader,
                runs,
                size,
                ref * reader.mft_record_size,
                reader.mft_record_size,
            )
            ext = _parse_record(raw, ref)
            if ext is None:
                retry.append((_type, _name, ref))
                continue
            seen.add(ref)
            progress = True
            for attr in ext.attrs:
                if attr.type == ATTR_DATA and not attr.name and not attr.resident:
                    runs.extend(attr.runs)
                    if attr.data_size > size:
                        size = attr.data_size
            for entry in _attr_list_entries(reader, ext.attrs):
                if (
                    entry[0] == ATTR_DATA
                    and not entry[1]
                    and entry[2] not in seen
                ):
                    retry.append(entry)
        pending = retry
        if not progress:
            break
    return runs, size


def _read_mft_bytes(reader, offset: int, size: int) -> bytes:
    return _read_runs(reader, reader._mft_runs, reader._mft_size, offset, size)


def _record(reader, mft_no: int) -> Optional[_Record]:
    if mft_no < 0:
        return None
    cached = reader._record_cache.get(mft_no, _MISSING)
    if cached is not _MISSING:
        reader._record_cache.move_to_end(mft_no)
        return cached
    if mft_no in reader._loading:
        return None

    reader._loading.add(mft_no)
    try:
        record: Optional[_Record] = None
        offset = mft_no * reader.mft_record_size
        if offset + reader.mft_record_size <= reader._mft_size:
            raw = _read_mft_bytes(reader, offset, reader.mft_record_size)
            record = _parse_record(raw, mft_no)

        if record is not None:
            base = record.base_ref & MFT_REF_MASK
            if base and base != mft_no:
                record = _record(reader, base)
            elif not (record.flags & FILE_RECORD_IN_USE):
                record = None
            else:
                record.attrs = _merge_extension_attrs(reader, record)
    finally:
        reader._loading.discard(mft_no)

    reader._record_cache[mft_no] = record
    if len(reader._record_cache) > reader._record_cache_limit:
        reader._record_cache.popitem(last=False)
    return record
