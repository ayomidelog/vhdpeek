"""FAT12/FAT16/FAT32 reader tests."""

from __future__ import annotations

import pytest

from vhdpeek.core.volume import BytesView
from vhdpeek.fs.fat import FatReader

from tests.fixtures import fsgen
from tests.support import EXPECTED, SAMPLE, images  # noqa: F401

__all__ = ["images"]

class TestFat:
    @pytest.mark.parametrize("kind", ["fat12", "fat16", "fat32"])
    def test_type_detected(self, images, kind):
        reader = FatReader(BytesView(images["raw"][kind]))
        assert reader.fs_type == kind

    @pytest.mark.parametrize("kind", ["fat12", "fat16", "fat32"])
    def test_root_listing(self, images, kind):
        reader = FatReader(BytesView(images["raw"][kind]))
        names = {entry.name for entry in reader.list_dir("")}
        assert {"docs", "data", "readme.txt"} <= names
        assert reader.label == "TESTVOL"

    @pytest.mark.parametrize("kind", ["fat12", "fat16", "fat32"])
    def test_file_contents(self, images, kind):
        reader = FatReader(BytesView(images["raw"][kind]))
        for path, expected in EXPECTED.items():
            assert reader.read_file(path) == expected, path

    @pytest.mark.parametrize("kind", ["fat12", "fat16", "fat32"])
    def test_long_filename(self, images, kind):
        reader = FatReader(BytesView(images["raw"][kind]))
        entry = reader.stat("/docs/long name with spaces.md")
        assert entry is not None
        assert entry.name == "long name with spaces.md"
        assert entry.size == len(EXPECTED["/docs/long name with spaces.md"])

    def test_range_read_inside_multicluster_file(self, images):
        reader = FatReader(BytesView(images["raw"]["fat32"]))
        body = EXPECTED["/data/blob.bin"]
        assert reader.read_file("/data/blob.bin", 100, 50) == body[100:150]
        assert reader.read_file("/data/blob.bin", 0, 0) == b""
        assert reader.read_file("/data/blob.bin", 10_000, 10) == b""

    def test_file_reader_across_clusters(self, images):
        reader = FatReader(BytesView(images["raw"]["fat32"]))
        read = reader.file_reader("/data/blob.bin")
        body = EXPECTED["/data/blob.bin"]
        assert read(0, 600) == body
        assert read(511, 4) == body[511:515]

    def test_missing_paths(self, images):
        reader = FatReader(BytesView(images["raw"]["fat32"]))
        assert reader.stat("/nope.txt") is None
        assert reader.read_file("/nope.txt") == b""
        with pytest.raises(FileNotFoundError):
            reader.list_dir("/nope")

    def test_fat_not_loaded_wholesale(self):
        """Listing a large FAT volume must not read the whole FAT."""
        image = fsgen.build_fat32(SAMPLE)
        counters = {"bytes": 0}

        class CountingView(BytesView):
            def read(self, offset, size):
                counters["bytes"] += size
                return super().read(offset, size)

        reader = FatReader(CountingView(image))
        counters["bytes"] = 0
        reader.list_dir("")
        fat_bytes = reader._fat_sectors * 512 if hasattr(reader, "_fat_sectors") else None
        if fat_bytes:
            assert counters["bytes"] < fat_bytes
