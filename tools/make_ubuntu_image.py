"""
Build a Ubuntu-desktop-like image for the end-to-end checks:

  60 GiB dynamic VHD
    MBR, one Linux partition at LBA 2048
      ext4
        /casper/ubuntu-24.04-desktop-amd64.iso   <- a real ISO inside ext4
        /etc/os-release, /boot/vmlinuz, ...

The virtual disk is sparse: only the blocks holding real data are stored, so
the file on disk stays a few megabytes while the virtual disk claims 60 GiB.

    python tools/make_ubuntu_image.py [--out ubuntu.vhd]
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.fixtures import fsgen, vhdgen

VIRTUAL_SIZE = 60 << 30          # 60 GiB
PART_START = 2048
BLOCK_SIZE = 2 << 20             # VHD container block

OS_RELEASE = (
    b'PRETTY_NAME="Ubuntu 24.04.1 LTS"\n'
    b'NAME="Ubuntu"\n'
    b'VERSION_ID="24.04"\n'
    b'VERSION="24.04.1 LTS (Noble Numbat)"\n'
    b'ID=ubuntu\n'
    b'ID_LIKE=debian\n'
)

ISO_FILES = {
    "casper/vmlinuz": b"\x7fELF" + b"\x00" * 4092,
    "casper/initrd": b"INITRD" + bytes(range(256)) * 400,
    "casper/filesystem.squashfs": b"hsqs" + bytes(range(256)) * 8000,
    "boot/grub/grub.cfg": b"set timeout=0\nmenuentry 'Try Ubuntu' {}\n",
    "README.diskdefines": b"#define DISKNAME Ubuntu 24.04.1 LTS\n",
    "pool/main/h/hello/hello_2.10.deb": b"!<arch>\n" + b"\x00" * 600,
    ".disk/info": b"Ubuntu 24.04.1 LTS amd64\n",
}


def build_ubuntu_disk() -> bytes:
    """ext4 with a nested ISO, wrapped in an MBR."""
    iso = fsgen.build_iso(ISO_FILES, joliet=True, rock_ridge=True,
                          volume_id="Ubuntu 24.04.1 LTS amd64")

    files = {
        "etc/os-release": OS_RELEASE,
        "etc/hostname": b"ubuntu\n",
        "boot/vmlinuz-6.8.0-45-generic": b"\x7fELF" + b"\x00" * 5000,
        "boot/grub/grub.cfg": b"set timeout=5\n",
        "home/ubuntu/.bashrc": b"# ~/.bashrc\nalias ll='ls -alF'\n",
        "casper/": b"",
        "casper/ubuntu-24.04-desktop-amd64.iso": iso,
        "var/log/installer/curtin-install.log": b"installer log\n" * 200,
    }
    ext4 = fsgen.build_ext4(files)
    return vhdgen.assemble_disk(ext4, "mbr", start_lba=PART_START,
                               mbr_type=0x83)


def to_sparse_vhd(disk: bytes, virtual_size: int = VIRTUAL_SIZE) -> bytes:
    """Store only the blocks that carry data."""
    blocks = {}
    for offset in range(0, len(disk), BLOCK_SIZE):
        chunk = disk[offset:offset + BLOCK_SIZE]
        if any(chunk):
            blocks[offset // BLOCK_SIZE] = chunk
    return vhdgen.wrap_sparse_vhd(blocks, virtual_size, BLOCK_SIZE)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="test_data/ubuntu.vhd")
    args = parser.parse_args()

    disk = build_ubuntu_disk()
    image = to_sparse_vhd(disk)
    path = Path(args.out)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(image)
    print(f"virtual {VIRTUAL_SIZE / (1 << 30):.0f} GiB, "
          f"stored {len(image):,} bytes -> {path}")


if __name__ == "__main__":
    main()
