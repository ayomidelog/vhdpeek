"""Text output: partition table, directory tree, listing, file streaming."""

from __future__ import annotations

import sys
from typing import List

from ..core.containers import VHDInfo
from ..core.partitions import Partition, parse_partitions
from ..core.volume import format_size

CHUNK = 1 << 20


def info(message: str = "") -> None:
    """Diagnostics go to stderr so `--cat` leaves stdout byte-exact."""
    print(message, file=sys.stderr)


def print_partitions(disk: VHDInfo) -> List[Partition]:
    parts = parse_partitions(disk)
    info("\n=== Partitions ===")
    if not parts:
        info("  (no partition table found)")
        return parts
    for part in parts:
        name = f"  {part.name}" if part.name else ""
        info(f"  [{part.index}] LBA {part.start_lba:>10} - "
             f"{part.end_lba:<10} {part.type:<20} "
             f"{format_size(part.size_bytes):>10}{name}")
    return parts


def print_tree(reader, path: str = "", max_depth: int = 3,
               prefix: str = "", depth: int = 0) -> None:
    if depth >= max_depth:
        return
    try:
        entries = reader.list_dir(path)
    except Exception as exc:
        print(f"{prefix}<error reading {path or '/'}: {exc}>")
        return
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        connector = "+-- " if last else "|-- "
        suffix = "/" if entry.is_dir else f"  ({format_size(entry.size)})"
        print(f"{prefix}{connector}{entry.name}{suffix}")
        if entry.is_dir:
            print_tree(reader, entry.path, max_depth,
                       prefix + ("    " if last else "|   "), depth + 1)


def print_listing(reader, path: str) -> None:
    entries = reader.list_dir(path)
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    for entry in entries:
        kind = "d" if entry.is_dir else "-"
        size = "" if entry.is_dir else format_size(entry.size)
        print(f"{kind} {size:>10}  {entry.name}")


def stream_file(reader, path: str) -> int:
    """Copy a file to stdout in chunks, bounded by its recorded size."""
    entry = reader.stat(path)
    if entry is None:
        raise FileNotFoundError(path)
    if entry.is_dir:
        raise IsADirectoryError(path)

    out = sys.stdout.buffer
    read = reader.file_reader(path)
    offset = 0
    while offset < entry.size:
        chunk = read(offset, min(CHUNK, entry.size - offset))
        if not chunk:
            break
        out.write(chunk)
        offset += len(chunk)
    out.flush()
    return offset
