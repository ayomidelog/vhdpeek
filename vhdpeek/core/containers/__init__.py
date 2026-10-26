"""
Container detection.

The caller hands over a `Source`; this decides whether it is a legacy VHD or
a VHDX and returns a `VHDInfo` whose `read` is the only thing the layers
above need.
"""

from __future__ import annotations

from ..errors import NotAnImage, UnknownSize
from ..source import Source
from . import vhd, vhdx
from .info import VHDInfo

__all__ = ["VHDInfo", "detect_and_parse"]

#: A VHD footer is 512 bytes; anything smaller cannot be a disk image.
MIN_SIZE = 512


def detect_and_parse(source: Source) -> VHDInfo:
    """
    Identify the container and return a readable virtual disk.

    Raises `UnknownSize` when the source will not report its length and
    `NotAnImage` when the bytes are not a VHD or VHDX.
    """
    file_size = source.size
    if file_size is None:
        raise UnknownSize(
            "cannot determine the image size",
            hint="the server did not send Content-Length or Content-Range",
        )
    if file_size < MIN_SIZE:
        raise NotAnImage(
            f"too small to be a disk image ({file_size} bytes)",
            hint="a VHD footer alone is 512 bytes",
        )

    if source.read(0, 8).lower() == vhdx.COOKIE:
        return vhdx.parse(source, file_size)

    if file_size >= 1024:
        if source.read(file_size - 512, 8) == vhd.COOKIE:
            return vhd.parse(source, file_size)

    raise NotAnImage(
        "not a VHD or VHDX image",
        hint="the file starts with "
             f"{_prefix(source)}, and neither container signature is present",
    )


def _prefix(source: Source) -> str:
    """The first bytes as hex, to help identify what the file actually is."""
    try:
        head = source.read(0, 8)
    except Exception:
        return "unreadable bytes"
    return head.hex(" ") if head else "nothing"
