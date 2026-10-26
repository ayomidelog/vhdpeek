"""Volume descriptor scanning and directory record decoding."""

from __future__ import annotations

import struct
from typing import Optional, Tuple

from .records import (_Extent, _IS_DIRECTORY, _Record, _RrInfo, _parse_time,
                      _strip_version)

_DESCRIPTOR_SIZE = 2048
_FIRST_DESCRIPTOR = 16
_MAX_DESCRIPTORS = 64
_ROOT_RECORD_OFFSET = 156


class _DescriptorMixin:
    @staticmethod
    def _valid_descriptor(desc: bytes) -> bool:
        """A real descriptor carries a plausible 34-byte root record."""
        if len(desc) < _ROOT_RECORD_OFFSET + 34:
            return False
        record = desc[_ROOT_RECORD_OFFSET:_ROOT_RECORD_OFFSET + 34]
        if record[0] != 34 or record[32] != 1 or record[33] != 0:
            return False
        if not (record[25] & _IS_DIRECTORY):
            return False
        lba = struct.unpack_from("<I", record, 2)[0]
        size = struct.unpack_from("<I", record, 10)[0]
        return lba > 0 and size > 0

    def _read_descriptors(self) -> Tuple[bytes, Optional[bytes]]:
        pvd: Optional[bytes] = None
        joliet: Optional[bytes] = None
        joliet_level = 0
        for sector in range(_FIRST_DESCRIPTOR,
                            _FIRST_DESCRIPTOR + _MAX_DESCRIPTORS):
            desc = self._view.read(sector * _DESCRIPTOR_SIZE,
                                   _DESCRIPTOR_SIZE)
            # The set terminator normally ends the scan, but some writers
            # put a Joliet descriptor after one.  Keep going while the
            # descriptors still carry the CD001 signature.
            if desc[1:6] != b"CD001":
                break
            dtype = desc[0]
            if dtype == 1 and pvd is None and self._valid_descriptor(desc):
                pvd = desc
            elif dtype == 2 and self._valid_descriptor(desc):
                escape = desc[88:120].rstrip(b"\x00 ")
                level = {b"%/@": 1, b"%/C": 2, b"%/E": 3}.get(escape, 0)
                if level > joliet_level:
                    joliet = desc
                    joliet_level = level
        if pvd is None:
            raise ValueError("not an ISO 9660 image: no primary descriptor")
        self._joliet_vd = joliet
        return pvd, joliet

    def _system_use_area(self, raw: bytes) -> bytes:
        name_len = raw[32]
        offset = 33 + name_len
        if name_len % 2 == 0:
            offset += 1
        return raw[offset:] if offset < len(raw) else b""

    def _detect_susp(self, root: _Record) -> bool:
        """Look for the SUSP ``SP`` entry in the root's dot record."""
        if not root.extents:
            return False
        raw = self._view.read(root.extents[0].offset, self._block_size)
        if len(raw) < 34:
            return False
        length = raw[0]
        if length < 34 or length > len(raw):
            return False
        area = self._system_use_area(raw[:length])
        pos = 0
        while pos + 7 <= len(area):
            tag = area[pos:pos + 2]
            entry_len = area[pos + 2]
            if entry_len < 4 or pos + entry_len > len(area):
                break
            if (tag == b"SP" and entry_len >= 7
                    and area[pos + 4:pos + 6] == b"\xbe\xef"):
                self._susp_skip = area[pos + 6]
                return True
            pos += entry_len
        return False

    def _parse_record(self, raw: bytes, joliet: bool) -> Optional[_Record]:
        if len(raw) < 34:
            return None
        name_len = raw[32]
        if 33 + name_len > len(raw):
            return None
        ext_attr = raw[1]
        lba = struct.unpack_from("<I", raw, 2)[0]
        size = struct.unpack_from("<I", raw, 10)[0]
        flags = raw[25]
        is_dir = bool(flags & _IS_DIRECTORY)
        identifier = raw[33:33 + name_len]
        name = self._decode_name(identifier, is_dir, joliet)
        mtime = _parse_time(raw[18:25])

        rr = self._parse_rr(raw) if self._has_rr else _RrInfo()
        if rr.name is not None:
            name = rr.name

        offset = (lba + ext_attr) * self._block_size
        extents = [_Extent(offset, size)]
        if rr.child_lba is not None:
            # Rock Ridge relocates deep directories: the visible record is a
            # placeholder whose CL entry points at the real extent.  Writers
            # such as pycdlib clear the directory flag on that placeholder,
            # so the CL entry is what makes it a directory.
            is_dir = True
            real_offset = rr.child_lba * self._block_size
            extents = [_Extent(real_offset,
                               self._directory_size(real_offset))]

        return _Record(name=name, identifier=identifier, is_dir=is_dir,
                       extents=extents, mtime=mtime, flags=flags,
                       relocated=rr.relocated)

    def _directory_size(self, offset: int) -> int:
        raw = self._view.read(offset, self._block_size)
        if len(raw) < 34:
            return self._block_size
        length = raw[0]
        if length < 34 or length > len(raw):
            return self._block_size
        return struct.unpack_from("<I", raw, 10)[0]

    def _decode_name(self, identifier: bytes, is_dir: bool,
                     joliet: bool) -> str:
        if identifier == b"\x00":
            return "."
        if identifier == b"\x01":
            return ".."
        if joliet:
            name = identifier.decode("utf-16-be", "replace").rstrip("\x00")
        else:
            name = identifier.decode("latin-1").rstrip("\x00")
        return name if is_dir else _strip_version(name)
