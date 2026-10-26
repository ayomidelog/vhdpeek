"""
Preview rendering: text when it is text, a hex dump otherwise.
"""

from __future__ import annotations

PREVIEW_LIMIT = 64 * 1024


def render(data: bytes) -> str:
    """
    Preview text for a byte sample.

    A file is shown as text when it decodes as UTF-8 and carries no control
    characters beyond tab/newline/carriage return; anything else gets a hex
    dump, because guessing wrong is worse than showing the bytes.
    """
    if not data:
        return "(empty file)"

    sample = data[:8192]
    if b"\x00" not in sample:
        try:
            text = sample.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            controls = sum(1 for ch in text
                           if ord(ch) < 32 and ch not in "\t\n\r")
            if controls * 100 <= len(text):
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return text

    lines = []
    per_line = 16
    for offset in range(0, len(data), per_line):
        row = data[offset:offset + per_line]
        hexes = " ".join(f"{b:02x}" for b in row)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        lines.append(f"{offset:08x}  {hexes:<47}  {ascii_}")
    return "\n".join(lines)
