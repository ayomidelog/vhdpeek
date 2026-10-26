"""Byte sources: local files and HTTP(S) with Range requests."""

from .source import (
    HTTPSource,
    LocalSource,
    RangeNotSupported,
    Source,
    make_source,
)

__all__ = [
    "Source",
    "LocalSource",
    "HTTPSource",
    "RangeNotSupported",
    "make_source",
]
