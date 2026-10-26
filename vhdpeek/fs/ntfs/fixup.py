"""Update-sequence-array fixups and FILE record parsing."""

from __future__ import annotations

from typing import List, Optional

from .records import (
    _Attr,
    _Record,
    _Run,
    _normalize_runs,
    _u16,
    _u32,
    _u64,
)


def _fixup(raw: bytes) -> Optional[bytes]:
    """Restore the original last two bytes of every 512-byte block."""
    if len(raw) < 8:
        return None
    usa_off = _u16(raw, 4)
    usa_count = _u16(raw, 6)
    expected = len(raw) // 512 + 1
    if usa_count != expected or usa_count < 2:
        return None
    if usa_off < 8 or usa_off + usa_count * 2 > len(raw):
        return None
    buf = bytearray(raw)
    usn = bytes(buf[usa_off:usa_off + 2])
    for index in range(1, usa_count):
        pos = index * 512 - 2
        if pos + 2 > len(buf) or bytes(buf[pos:pos + 2]) != usn:
            return None
        buf[pos:pos + 2] = buf[usa_off + index * 2:usa_off + index * 2 + 2]
    return bytes(buf)


def _parse_record(raw: bytes, number: int) -> Optional[_Record]:
    if len(raw) < 0x30 or raw[:4] != b"FILE":
        return None
    buf = _fixup(raw)
    if buf is None:
        return None
    first_attr = _u16(buf, 0x14)
    used = _u32(buf, 0x18)
    if used > len(buf):
        used = len(buf)
    if first_attr < 0x18 or first_attr >= used:
        return None
    attrs = _parse_attrs(buf, first_attr, used)
    return _Record(
        number=number,
        sequence=_u16(buf, 0x10),
        flags=_u16(buf, 0x16),
        attrs=attrs,
        base_ref=_u64(buf, 0x20),
    )


def _parse_attrs(buf: bytes, start: int, limit: int) -> List[_Attr]:
    attrs: List[_Attr] = []
    pos = start
    while pos + 8 <= limit:
        attr_type = _u32(buf, pos)
        if attr_type in (0, 0xFFFFFFFF):
            break
        length = _u32(buf, pos + 4)
        if length < 0x18 or pos + length > limit:
            break

        non_resident = buf[pos + 8]
        name_len = buf[pos + 9]
        name_off = _u16(buf, pos + 0x0A)
        flags = _u16(buf, pos + 0x0C)

        name = ""
        if name_len:
            name_start = pos + name_off
            if name_off < 0x18 or name_start + name_len * 2 > pos + length:
                pos += (length + 7) & ~7
                continue
            name = buf[name_start:name_start + name_len * 2].decode(
                "utf-16-le", "replace"
            )

        if not non_resident:
            value_len = _u32(buf, pos + 0x10)
            value_off = _u16(buf, pos + 0x14)
            value_start = pos + value_off
            if value_len == 0:
                value = b""
            elif value_off < 0x18 or value_start + value_len > pos + length:
                value = b""
            else:
                value = bytes(buf[value_start:value_start + value_len])
            attrs.append(
                _Attr(
                    type=attr_type,
                    name=name,
                    flags=flags,
                    resident=True,
                    value=value,
                    data_size=len(value),
                    initialized_size=len(value),
                )
            )
        else:
            if length < 0x40:
                pos += (length + 7) & ~7
                continue
            start_vcn = _u64(buf, pos + 0x10)
            runs_off = _u16(buf, pos + 0x20)
            compression_unit = _u16(buf, pos + 0x22)
            runs_start = pos + runs_off
            runs_end = pos + length
            if runs_off < 0x40 or runs_start > runs_end:
                runs: List[_Run] = []
            else:
                runs = _normalize_runs(
                    _parse_runs(buf, runs_start, runs_end, start_vcn)
                )
            data_size = _u64(buf, pos + 0x30)
            init_size = _u64(buf, pos + 0x38)
            attrs.append(
                _Attr(
                    type=attr_type,
                    name=name,
                    flags=flags,
                    resident=False,
                    runs=runs,
                    data_size=data_size,
                    initialized_size=init_size,
                    compression_unit=compression_unit,
                )
            )

        pos += (length + 7) & ~7
    return attrs


def _parse_runs(
    buf: bytes, start: int, end: int, start_vcn: int
) -> List[_Run]:
    runs: List[_Run] = []
    pos = start
    vcn = start_vcn
    prev_lcn = 0
    while pos < end:
        header = buf[pos]
        pos += 1
        if header == 0:
            break
        len_size = header & 0x0F
        off_size = header >> 4
        if len_size == 0 or pos + len_size + off_size > end:
            break
        count = int.from_bytes(buf[pos:pos + len_size], "little")
        pos += len_size
        if count == 0:
            break
        if off_size:
            delta = int.from_bytes(
                buf[pos:pos + off_size], "little", signed=True
            )
            pos += off_size
            lcn = prev_lcn + delta
            if lcn < 0:
                break
            prev_lcn = lcn
            runs.append(_Run(vcn, lcn, count))
        else:
            runs.append(_Run(vcn, None, count))
        vcn += count
    return runs
