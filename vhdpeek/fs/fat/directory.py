"""FAT directory parsing: short entries, long names and the volume label."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ...core.volume import Entry, join_path
from .bpb import _u16, _u32
from .names import (
    _assemble_lfn,
    _clean_label,
    _fat_timestamp,
    _lfn_chunk,
    _short_checksum,
    _short_name,
)

_LFN_ATTR = 0x0F
_VOLUME_ATTR = 0x08
_DIR_ATTR = 0x10

def _parse_dir(data: bytes, prefix: str, label: Optional[str],
               fat_type: str) -> Tuple[List[Entry], Optional[str]]:
    """
    Parse a directory's raw bytes.

    Returns the entries and the label to use afterwards: the BPB copy is
    authoritative when present, and the root-directory volume entry only
    fills in when the BPB has no label, so the result does not depend on the
    order directories are parsed in.
    """
    entries: List[Entry] = []
    lfn: Dict[int, str] = {}
    lfn_checksum: Optional[int] = None

    for offset in range(0, len(data) - 31, 32):
        raw = data[offset:offset + 32]
        first = raw[0]
        if first == 0x00:                       # end of directory
            break
        if first == 0xE5:                       # deleted entry
            lfn.clear()
            lfn_checksum = None
            continue

        attr = raw[11]
        if attr == _LFN_ATTR:
            seq = first & 0x1F
            if 1 <= seq <= 20:
                lfn[seq] = _lfn_chunk(raw)
                lfn_checksum = raw[13]
            else:
                lfn.clear()
                lfn_checksum = None
            continue

        name = _short_name(raw)
        if attr & _VOLUME_ATTR:
            if label is None:
                label = _clean_label(raw[0:11])
            lfn.clear()
            lfn_checksum = None
            continue

        if (lfn and lfn_checksum is not None
                and _short_checksum(raw[0:11]) == lfn_checksum):
            long_name = _assemble_lfn(lfn)
            if long_name:
                name = long_name
        lfn.clear()
        lfn_checksum = None

        if not name or name in (".", ".."):
            continue

        cluster = _u16(raw, 26)
        if fat_type == "FAT32":
            cluster |= _u16(raw, 20) << 16
            cluster &= 0x0FFFFFFF
        is_dir = bool(attr & _DIR_ATTR)
        entries.append(Entry(
            name=name,
            path=join_path(prefix, name),
            is_dir=is_dir,
            size=0 if is_dir else _u32(raw, 28),
            mtime=_fat_timestamp(_u16(raw, 24), _u16(raw, 22)),
            extra={"first_cluster": cluster, "attributes": attr},
        ))
    return entries, label
