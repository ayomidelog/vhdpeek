"""FAT name, label and timestamp helpers."""

from __future__ import annotations

import calendar
from typing import Dict, Optional

def _ascii_lower(text: str) -> str:
    """Lowercase A-Z only; the NT lowercase flags never apply to OEM bytes."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)

def _short_checksum(short_name: bytes) -> int:
    """Checksum of an 11-byte 8.3 name, used to tie LFN entries to it."""
    value = 0
    for byte in short_name:
        value = (((value & 1) << 7) + (value >> 1) + byte) & 0xFF
    return value

def _lfn_chunk(raw: bytes) -> str:
    """The 13 UTF-16 code units held by one long-filename entry."""
    return (raw[1:11] + raw[14:26] + raw[28:32]).decode("utf-16-le", "replace")

def _assemble_lfn(parts: Dict[int, str]) -> str:
    """Join the sequence-numbered LFN fragments into a name, or "" if broken."""
    if not parts:
        return ""
    count = max(parts)
    if set(parts) != set(range(1, count + 1)):
        return ""
    text = "".join(parts[seq] for seq in range(1, count + 1))
    nul = text.find("\x00")
    if nul >= 0:
        text = text[:nul]
    return text.rstrip("\uffff")

def _fat_timestamp(date: int, time: int) -> Optional[int]:
    """FAT date/time words (last write) -> unix seconds, or None if unset."""
    if not date:
        return None
    year = 1980 + (date >> 9)
    month = (date >> 5) & 0x0F
    day = date & 0x1F
    hour = time >> 11
    minute = (time >> 5) & 0x3F
    second = (time & 0x1F) * 2
    try:
        return calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))
    except (ValueError, OverflowError):
        return None

def _short_name(raw: bytes) -> str:
    """The 8.3 name of an entry, honouring the NT lowercase flags."""
    base = bytearray(raw[0:8])
    if base[0] == 0x05:          # 0xE5 stored as 0x05 to avoid the free marker
        base[0] = 0xE5
    name = bytes(base).decode("cp437").rstrip(" ")
    ext = raw[8:11].decode("cp437").rstrip(" ")
    flags = raw[12]
    if flags & 0x08:
        name = _ascii_lower(name)
    if flags & 0x10:
        ext = _ascii_lower(ext)
    return name + "." + ext if ext else name

def _clean_label(raw: bytes) -> Optional[str]:
    label = raw.decode("cp437").rstrip("\x00 ").strip()
    if not label or label.upper() == "NO NAME":
        return None
    return label
