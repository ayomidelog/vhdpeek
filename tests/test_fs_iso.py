"""ISO9660 reader tests."""

from __future__ import annotations

from vhdpeek.core.volume import BytesView
from vhdpeek.fs.iso import IsoReader

from tests.support import EXPECTED, images  # noqa: F401

__all__ = ["images"]

class TestIso:
    def test_root_listing(self, images):
        data = images["raw"]["iso"]
        reader = IsoReader(BytesView(data, sector_size=2048))
        names = {entry.name for entry in reader.list_dir("")}
        assert {"docs", "data", "readme.txt"} <= names

    def test_file_contents(self, images):
        data = images["raw"]["iso"]
        reader = IsoReader(BytesView(data, sector_size=2048))
        for path, expected in EXPECTED.items():
            assert reader.read_file(path) == expected, path

    def test_nested_directory(self, images):
        data = images["raw"]["iso"]
        reader = IsoReader(BytesView(data, sector_size=2048))
        assert reader.read_file("/data/sub/note.txt") == EXPECTED[
            "/data/sub/note.txt"]
