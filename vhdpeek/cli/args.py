"""Argument parsing for the CLI."""

from __future__ import annotations

import argparse

FS_CHOICES = ["auto", "ntfs", "fat", "ext", "iso"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vhdpeek",
        description="Browse VHD/VHDX images over HTTP or from a local file.",
    )
    parser.add_argument("path", nargs="?",
                        help="local image path or http(s) URL")
    parser.add_argument("--gui", action="store_true",
                        help="open the graphical browser instead")
    parser.add_argument("--theme", choices=["dark", "light"], default=None,
                        help="GUI colour scheme (default: follow the system)")
    parser.add_argument("--parts", "--list-parts", action="store_true",
                        dest="parts", help="list partitions and stop")
    parser.add_argument("--part", type=int, default=None,
                        help="partition index (default: first with a filesystem)")
    parser.add_argument("--tree", action="store_true",
                        help="print the directory tree (default)")
    parser.add_argument("--max-depth", type=int, default=3,
                        help="tree depth limit (default: 3)")
    parser.add_argument("--ls", metavar="PATH",
                        help="list one directory")
    parser.add_argument("--cat", metavar="PATH",
                        help="stream a file to stdout")
    parser.add_argument("--iso", metavar="PATH",
                        help="mount an ISO stored inside the filesystem")
    parser.add_argument("--fs", choices=FS_CHOICES, default="auto",
                        help="override filesystem detection")
    return parser
