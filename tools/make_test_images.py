"""Regenerate the filesystem and VHD/VHDX images used by the test suite.

Usage:
    python tools/make_test_images.py [--out test_data]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixtures import fsgen, vhdgen

SAMPLE = {
    "readme.txt": b"Hello from vhdpeek test\nLine 2\n",
    "docs/": b"",
    "docs/manual.txt": b"Manual content\n",
    "docs/long name with spaces.md": b"long filename body\n",
    "data/": b"",
    "data/blob.bin": b"\x00\x01\x02\x03\x04\x05" * 100,
    "data/sub/": b"",
    "data/sub/note.txt": b"nested note\n",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate test images")
    parser.add_argument("--out", default="test_data")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "test_fat32.img").write_bytes(fsgen.build_fat32(SAMPLE))
    (out / "test_fat16.img").write_bytes(fsgen.build_fat16(SAMPLE))
    (out / "test_fat12.img").write_bytes(fsgen.build_fat12(SAMPLE))
    (out / "test_ntfs.img").write_bytes(fsgen.build_ntfs(SAMPLE))
    (out / "test_ext4.img").write_bytes(fsgen.build_ext4(SAMPLE))
    (out / "test_iso.iso").write_bytes(fsgen.build_iso(SAMPLE))

    disk = vhdgen.assemble_disk(fsgen.build_fat32(SAMPLE), "mbr", start_lba=1)
    (out / "test_fixed.vhd").write_bytes(vhdgen.wrap_fixed_vhd(disk))
    (out / "test_dynamic.vhd").write_bytes(vhdgen.wrap_dynamic_vhd(disk))
    (out / "test_vhdx.vhdx").write_bytes(vhdgen.wrap_vhdx(disk))

    print(f"wrote filesystem and VHD images to {out}")


if __name__ == "__main__":
    main()
