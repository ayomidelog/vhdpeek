"""CLI entry point."""

from __future__ import annotations

import sys
from typing import List, Optional

from ..core.containers import detect_and_parse
from ..core.partitions import PartitionView
from ..core.source import make_source
from ..core.volume import format_size
from ..fs import mount_iso, open_reader, probe
from .args import build_parser
from .render import info, print_listing, print_partitions, print_tree, stream_file


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from ..gui import main as gui_main
        return gui_main([args.path] if args.path else [])

    if not args.path:
        parser.error("a path or URL is required unless --gui is used")

    source = make_source(args.path)
    disk = detect_and_parse(source)

    info(f"Source: {args.path}")
    info(f"Format: {disk.describe()}")
    if disk.parent_name:
        info(f"Parent: {disk.parent_name} (not resolved)")
    if disk.is_dirty:
        info("Warning: VHDX log is not empty; the image was not cleanly "
             "closed and reads may be stale.")

    partitions = print_partitions(disk)
    if args.parts or not partitions:
        return 0

    chosen = _choose_partition(disk, partitions, args.part)
    if chosen is None:
        return 1

    view = PartitionView(disk, chosen)
    kind = args.fs if args.fs != "auto" else probe(view)
    if kind == "unknown":
        info(f"\nPartition {chosen.index}: unrecognised filesystem")
        return 1

    info(f"\n=== Partition {chosen.index}: {kind} ===")

    reader = open_reader(view, kind=kind)
    if args.iso:
        reader = mount_iso(reader, args.iso)
        info(f"ISO:    {reader.volume_id or '(unnamed)'}  "
             f"{format_size(reader.volume_size)}  "
             f"joliet={'yes' if reader.has_joliet else 'no'}  "
             f"rock-ridge={'yes' if reader.has_rock_ridge else 'no'}")

    if args.cat:
        stream_file(reader, args.cat)
        return 0
    if args.ls is not None:
        print_listing(reader, args.ls)
        return 0
    print_tree(reader, "", max_depth=args.max_depth)
    return 0


def _choose_partition(disk, partitions, wanted: Optional[int]):
    """The requested partition, or the first one holding a filesystem."""
    if wanted is not None:
        if not 0 <= wanted < len(partitions):
            info(f"No partition {wanted}")
            return None
        return partitions[wanted]

    for part in partitions:
        if probe(PartitionView(disk, part)) != "unknown":
            return part
    info("\nNo recognisable filesystem in any partition.")
    return None


if __name__ == "__main__":
    sys.exit(main())
