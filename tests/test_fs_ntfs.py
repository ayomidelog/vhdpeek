"""NTFS reader tests."""

from __future__ import annotations

from vhdpeek.core.volume import BytesView
from vhdpeek.fs.ntfs import NtfsReader

from tests.support import EXPECTED, images  # noqa: F401

__all__ = ["images"]

class TestNtfs:
    def test_root_listing(self, images):
        reader = NtfsReader(BytesView(images["raw"]["ntfs"]))
        names = {entry.name for entry in reader.list_dir("")}
        assert {"docs", "data", "readme.txt"} <= names

    def test_file_contents(self, images):
        reader = NtfsReader(BytesView(images["raw"]["ntfs"]))
        for path, expected in EXPECTED.items():
            assert reader.read_file(path) == expected, path

    def test_resident_and_nonresident(self, images):
        reader = NtfsReader(BytesView(images["raw"]["ntfs"]))
        small = reader.stat("/readme.txt")
        large = reader.stat("/data/blob.bin")
        assert small is not None and small.size == len(EXPECTED["/readme.txt"])
        assert large is not None and large.size == 600
        assert reader.read_file("/data/blob.bin", 10, 5) == EXPECTED[
            "/data/blob.bin"][10:15]

    def test_nested(self, images):
        reader = NtfsReader(BytesView(images["raw"]["ntfs"]))
        assert reader.read_file("/data/sub/note.txt") == EXPECTED[
            "/data/sub/note.txt"]
