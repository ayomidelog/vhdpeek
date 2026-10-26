"""Container format tests: fixed/dynamic VHD, VHDX and the large sparse shape."""

from __future__ import annotations

from pathlib import Path

import pytest

from vhdpeek.core.containers import detect_and_parse
from vhdpeek.core.partitions import PartitionView, parse_partitions
from vhdpeek.core.source import LocalSource, make_source
from vhdpeek.core.volume import BytesView, ReaderView
from vhdpeek.fs.ext4 import Ext4Reader
from vhdpeek.fs.iso import IsoReader

from tests.support import http_server, images, open_disk  # noqa: F401

__all__ = ["images", "http_server"]

class TestContainers:
    def test_fixed(self, images):
        disk = open_disk(images["containers"]["fixed"])
        assert disk.disk_type == "fixed"
        assert disk.logical_sector_size == 512
        assert disk.virtual_size == len(images["disk"])

    def test_dynamic(self, images):
        disk = open_disk(images["containers"]["dynamic"])
        assert disk.disk_type == "dynamic"
        assert disk.block_size == 2 << 20
        assert disk.sector_bitmap_size == 512

    def test_vhdx(self, images):
        disk = open_disk(images["containers"]["vhdx"])
        assert disk.disk_type == "vhdx"
        assert disk.block_size == 2 << 20
        assert disk.logical_sector_size == 512
        assert disk.physical_sector_size == 4096
        assert disk.is_dirty is False

    @pytest.mark.parametrize("kind", ["fixed", "dynamic", "vhdx"])
    def test_virtual_disk_contents_match(self, images, kind):
        """All three containers must expose byte-identical virtual disks."""
        disk = open_disk(images["containers"][kind])
        expected = images["disk"]
        assert disk.read(0, len(expected)) == expected

    @pytest.mark.parametrize("kind", ["fixed", "dynamic", "vhdx"])
    def test_unaligned_reads(self, images, kind):
        disk = open_disk(images["containers"][kind])
        expected = images["disk"]
        assert disk.read(1, 511) == expected[1:512]
        assert disk.read(511, 3) == expected[511:514]
        assert disk.read(len(expected) - 10, 100) == expected[-10:]

    def test_read_past_end_is_clamped(self, images):
        disk = open_disk(images["containers"]["fixed"])
        assert disk.read(disk.virtual_size, 512) == b""
        tail = disk.read(disk.virtual_size - 4, 512)
        assert len(tail) == 4

    def test_not_a_disk(self, tmp_path):
        path = tmp_path / "junk.bin"
        path.write_bytes(b"\x00" * 4096)
        with pytest.raises(ValueError):
            detect_and_parse(LocalSource(str(path)))

    def test_truncated_image_rejected(self, tmp_path):
        path = tmp_path / "tiny.bin"
        path.write_bytes(b"conectix")
        with pytest.raises(ValueError):
            detect_and_parse(LocalSource(str(path)))

# ---------------------------------------------------------------------------
# Large sparse image with a nested ISO (the 60 GiB Ubuntu shape)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ubuntu(images):
    from tools import make_ubuntu_image as ubuntu_gen

    disk = ubuntu_gen.build_ubuntu_disk()
    image = ubuntu_gen.to_sparse_vhd(disk)
    return {"bytes": image, "disk": disk, "gen": ubuntu_gen}

class TestLargeSparseImage:
    def test_virtual_size_and_holes(self, ubuntu):
        disk = detect_and_parse(BytesView(ubuntu["bytes"]))
        assert disk.virtual_size == 60 << 30
        assert disk.disk_type == "dynamic"
        assert len(ubuntu["bytes"]) < 64 << 20

        # Beyond the partition the disk is unallocated: reads must be zeros.
        hole = disk.read(30 << 30, 4096)
        assert hole == b"\x00" * 4096

        # Data that was stored must read back exactly.
        expected = ubuntu["disk"]
        assert disk.read(0, len(expected)) == expected

    def test_partition_and_filesystem_at_high_offset(self, ubuntu):
        disk = detect_and_parse(BytesView(ubuntu["bytes"]))
        parts = parse_partitions(disk)
        assert len(parts) == 1
        assert parts[0].start_lba == 2048

        reader = Ext4Reader(PartitionView(disk, parts[0]))
        assert reader.read_file("/etc/os-release").startswith(b'PRETTY_NAME="Ubuntu')

    def test_nested_iso_is_browsable_unmounted(self, ubuntu):
        disk = detect_and_parse(BytesView(ubuntu["bytes"]))
        ext = Ext4Reader(PartitionView(disk, parse_partitions(disk)[0]))
        entry = ext.stat("/casper/ubuntu-24.04-desktop-amd64.iso")
        assert entry is not None

        iso = IsoReader(ReaderView(ext.file_reader(entry.path), entry.size))
        names = {item.name for item in iso.list_dir("")}
        assert {"casper", "boot", "pool"} <= names
        assert iso.read_file("/casper/initrd") == ubuntu["gen"].ISO_FILES[
            "casper/initrd"]
        assert iso.read_file("/casper/vmlinuz")[:4] == b"\x7fELF"

    def test_http_fetches_a_tiny_fraction(self, http_server, ubuntu, images):
        """Browsing a 60 GiB image must not download it."""
        from tools import make_ubuntu_image as ubuntu_gen

        target = Path(images["dir"]) / "ubuntu.vhd"
        target.write_bytes(ubuntu_gen.to_sparse_vhd(
            ubuntu_gen.build_ubuntu_disk()))

        source = make_source(f"{http_server}/ubuntu.vhd")
        disk = detect_and_parse(source)
        assert disk.virtual_size == 60 << 30

        ext = Ext4Reader(PartitionView(disk, parse_partitions(disk)[0]))
        entry = ext.stat("/casper/ubuntu-24.04-desktop-amd64.iso")
        iso = IsoReader(ReaderView(ext.file_reader(entry.path), entry.size))
        assert iso.read_file("/casper/vmlinuz")[:4] == b"\x7fELF"

        stored = target.stat().st_size
        assert source.bytes_fetched < stored
        assert source.bytes_fetched < 8 << 20
        target.unlink()
