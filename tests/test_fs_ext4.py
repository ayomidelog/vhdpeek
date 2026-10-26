"""ext4 reader tests."""

from __future__ import annotations

from vhdpeek.core.partitions import PartitionView, parse_partitions
from vhdpeek.core.volume import BytesView
from vhdpeek.fs.ext4 import Ext4Reader

from tests.support import EXPECTED, images, open_disk  # noqa: F401

__all__ = ["images"]

class TestExt4:
    def test_root_listing(self, images):
        reader = Ext4Reader(BytesView(images["raw"]["ext4"]))
        names = {entry.name for entry in reader.list_dir("")}
        assert {"docs", "data", "readme.txt"} <= names

    def test_file_contents(self, images):
        reader = Ext4Reader(BytesView(images["raw"]["ext4"]))
        for path, expected in EXPECTED.items():
            assert reader.read_file(path) == expected, path

    def test_nested(self, images):
        reader = Ext4Reader(BytesView(images["raw"]["ext4"]))
        assert reader.read_file("/data/sub/note.txt") == EXPECTED[
            "/data/sub/note.txt"]

    def test_gpt_partition_filesystem(self, images):
        disk = open_disk(images["containers"]["gpt_ext4"])
        part = parse_partitions(disk)[0]
        reader = Ext4Reader(PartitionView(disk, part))
        assert reader.read_file("/readme.txt") == EXPECTED["/readme.txt"]
