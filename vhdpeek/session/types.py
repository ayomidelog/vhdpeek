"""
Session result types.

These are plain data: no toolkit, no I/O. The GUI renders them, the CLI
prints them, tests compare them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..core.volume import format_size


@dataclass
class ImageInfo:
    path: str
    remote: bool
    disk_type: str
    virtual_size: int
    file_size: int
    sector_size: int
    block_size: int
    is_dirty: bool = False
    parent_name: Optional[str] = None

    @property
    def summary(self) -> str:
        return (f"{self.disk_type.upper()}  ·  virtual "
                f"{format_size(self.virtual_size)}  ·  "
                f"{'remote' if self.remote else 'file'} "
                f"{format_size(self.file_size)}")


@dataclass
class Scope:
    """
    Something with a filesystem the session can read.

    `id` is stable for the lifetime of the session and is what every path
    operation names. `kind` is "partition" or "iso".
    """

    id: str
    kind: str
    label: str
    fs_type: str
    detail: str = ""
    # For an ISO: where it came from, so the tree can nest it under the file.
    parent_scope: Optional[str] = None
    parent_path: Optional[str] = None
    index: Optional[int] = None
    size_bytes: int = 0


@dataclass
class VolumeInfo:
    """A partition, whether or not it holds a filesystem we understand."""

    index: int
    start_lba: int
    end_lba: int
    type: str
    name: Optional[str]
    size_bytes: int
    scheme: str
    fs_type: str = "unknown"
    label: str = ""

    @property
    def title(self) -> str:
        return f"Partition {self.index}"

    @property
    def subtitle(self) -> str:
        if self.fs_type == "unknown":
            return f"{self.type}  ·  {format_size(self.size_bytes)}"
        label = f"{self.label}  ·  " if self.label else ""
        return f"{label}{self.fs_type}  ·  {format_size(self.size_bytes)}"
