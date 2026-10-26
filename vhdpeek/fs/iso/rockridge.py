"""Rock Ridge / SUSP parsing."""

from __future__ import annotations

import struct
from typing import Set, Tuple

from .records import _RrInfo, _decode_rr_name

_MAX_CE_DEPTH = 8
_MAX_CE_LENGTH = 1 << 20


class _RockRidgeMixin:
    def _parse_rr(self, raw: bytes) -> _RrInfo:
        info = _RrInfo()
        area = self._system_use_area(raw)
        if not area:
            return info
        start = self._susp_skip if self._susp_skip < len(area) else 0
        self._scan_susp(area[start:], info, 0, set())
        return info

    def _scan_susp(self, area: bytes, info: _RrInfo, depth: int,
                   seen: Set[Tuple[int, int, int]]) -> None:
        pos = 0
        while pos + 4 <= len(area):
            tag = area[pos:pos + 2]
            length = area[pos + 2]
            if length < 4 or pos + length > len(area):
                break
            entry = area[pos:pos + length]
            if tag == b"ST":
                break
            if tag == b"SP":
                if length >= 7 and entry[4:6] == b"\xbe\xef":
                    self._susp_skip = entry[6]
            elif tag == b"NM":
                flags = entry[4]
                data = entry[5:]
                info.name_bytes += data
                if not (flags & 0x01):
                    if info.name_bytes:
                        info.name = _decode_rr_name(info.name_bytes)
                        info.name_bytes = b""
                    elif flags & 0x02:
                        info.name = "."
                    elif flags & 0x04:
                        info.name = ".."
            elif tag == b"CE":
                if length >= 28 and depth < _MAX_CE_DEPTH:
                    block = struct.unpack_from("<I", entry, 4)[0]
                    offset = struct.unpack_from("<I", entry, 12)[0]
                    ce_length = struct.unpack_from("<I", entry, 20)[0]
                    key = (block, offset, ce_length)
                    if (block > 0 and 0 < ce_length <= _MAX_CE_LENGTH
                            and key not in seen):
                        seen.add(key)
                        continuation = self._view.read(
                            block * self._block_size + offset, ce_length)
                        start = (self._susp_skip
                                 if self._susp_skip < len(continuation) else 0)
                        self._scan_susp(continuation[start:], info,
                                        depth + 1, seen)
            elif tag == b"CL":
                if length >= 12:
                    child_lba = struct.unpack_from("<I", entry, 4)[0]
                    if child_lba > 0:
                        info.child_lba = child_lba
            elif tag == b"RE":
                info.relocated = True
            elif tag == b"SK":
                # The SK entry's payload is padding; advancing by its length
                # is exactly the required skip.
                pass
            pos += length
