"""
Container detection.

The caller hands over a `Source`; this decides whether it is a legacy VHD or
a VHDX and returns a `VHDInfo` whose `read` is the only thing the layers
above need.
"""

from __future__ import annotations

from ..source import Source
from . import vhd, vhdx
from .info import VHDInfo

__all__ = ["VHDInfo", "detect_and_parse"]


def detect_and_parse(source: Source) -> VHDInfo:
    """Identify the container and return a readable virtual disk."""
    file_size = source.size
    if file_size is None:
        raise ValueError(
            "cannot determine image size; the server did not report "
            "Content-Length or Content-Range"
        )
    if file_size < 512:
        raise ValueError(f"image too small to be a disk ({file_size} bytes)")

    if source.read(0, 8).lower() == vhdx.COOKIE:
        return vhdx.parse(source, file_size)

    if file_size >= 1024:
        if source.read(file_size - 512, 8) == vhd.COOKIE:
            return vhd.parse(source, file_size)

    raise ValueError("not a recognised VHD or VHDX image")
