"""
Build the Windows icon from the source artwork.

`assets/vhd_ico.png` is a square lockup: the mark on top, the wordmark below.
An .ico is displayed as small as 16 px, where the wordmark is unreadable, so
this crops to the mark and pads it back to a square.

    python tools/make_icon.py

Run it after changing the artwork; the result is committed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "vhd_ico.png"
TARGET = ROOT / "assets" / "vhdpeek.ico"

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
         (128, 128), (256, 256)]

#: Fraction of the icon left as margin on each side.
MARGIN = 0.06


def find_gap(image) -> int:
    """
    The first row of a wide empty band, i.e. where the mark ends.

    Scanning with a stride keeps this quick on a large source, and a wide band
    is what separates the mark from the wordmark - a gap between, say, the
    disc and the handle is far narrower.
    """
    width, height = image.size
    pixels = image.load()
    empty = []
    for y in range(height):
        filled = False
        for x in range(0, width, 3):
            r, g, b = pixels[x, y][:3]
            if r + g + b < 720:
                filled = True
                break
        empty.append(not filled)

    # Skip the leading margin: the artwork does not start at row 0.
    first = next((y for y, is_empty in enumerate(empty) if not is_empty), height)

    start = None
    for y in range(first, height):
        if empty[y]:
            if start is None:
                start = y
        elif start is not None:
            if y - start >= 24:
                return start
            start = None
    return height


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required: python -m pip install pillow", file=sys.stderr)
        return 1

    if not SOURCE.is_file():
        print(f"missing source artwork: {SOURCE}", file=sys.stderr)
        return 1

    image = Image.open(SOURCE).convert("RGB")
    cut = find_gap(image)
    mark = image.crop((0, 0, image.width, cut))

    # Trim the surrounding whitespace, then pad to a square so the mark is
    # centred rather than stretched.
    box = _content_box(mark)
    mark = mark.crop(box)

    side = int(max(mark.size) * (1 + 2 * MARGIN))
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2))

    canvas.save(TARGET, sizes=SIZES)
    print(f"wrote {TARGET.relative_to(ROOT)} ({side}x{side}, "
          f"{len(SIZES)} sizes) from rows 0-{cut} of the source")
    return 0


def _content_box(image):
    """Bounding box of the non-white pixels."""
    width, height = image.size
    pixels = image.load()
    left, top, right, bottom = width, height, 0, 0
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            r, g, b = pixels[x, y][:3]
            if r + g + b < 720:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right <= left or bottom <= top:
        return (0, 0, width, height)
    return (max(0, left - 2), max(0, top - 2),
            min(width, right + 3), min(height, bottom + 3))


if __name__ == "__main__":
    sys.exit(main())
