"""Filesystem detection and the reader registry."""

from __future__ import annotations

import pytest

from vhdpeek.core.volume import BytesView
from vhdpeek.fs import (Ext4Reader, FatReader, IsoReader, NtfsReader,
                       looks_like_iso, mount_iso, open_reader, probe)

from tests.fixtures import fsgen

SAMPLE = {"readme.txt": b"hello\n", "docs/": b"", "docs/a.txt": b"a\n"}


class TestProbe:
    @pytest.mark.parametrize("builder,kind", [
        (fsgen.build_fat12, "fat12"),
        (fsgen.build_fat16, "fat16"),
        (fsgen.build_fat32, "fat32"),
        (fsgen.build_ntfs, "ntfs"),
        (fsgen.build_ext4, "ext"),
        (fsgen.build_iso, "iso"),
    ])
    def test_identifies_each_filesystem(self, builder, kind):
        assert probe(BytesView(builder(SAMPLE))) == kind

    def test_blank_region_is_unknown(self):
        assert probe(BytesView(b"\x00" * 8192)) == "unknown"


class TestOpenReader:
    @pytest.mark.parametrize("builder,reader_class", [
        (fsgen.build_fat32, FatReader),
        (fsgen.build_ntfs, NtfsReader),
        (fsgen.build_ext4, Ext4Reader),
        (fsgen.build_iso, IsoReader),
    ])
    def test_returns_the_matching_reader(self, builder, reader_class):
        reader = open_reader(BytesView(builder(SAMPLE)))
        assert isinstance(reader, reader_class)

    def test_explicit_kind_skips_detection(self):
        # FAT12 bytes, but the caller insists it is FAT.
        reader = open_reader(BytesView(fsgen.build_fat12(SAMPLE)), kind="fat")
        assert isinstance(reader, FatReader)

    def test_unknown_region_raises(self):
        with pytest.raises(ValueError, match="unsupported filesystem"):
            open_reader(BytesView(b"\x00" * 8192))

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="unsupported filesystem"):
            open_reader(BytesView(fsgen.build_fat32(SAMPLE)), kind="zfs")


class TestMountIso:
    def test_mounts_an_iso_stored_in_a_filesystem(self):
        inner = fsgen.build_iso({"inner.txt": b"nested\n"})
        outer = fsgen.build_ext4({"boot/": b"", "boot/x.iso": inner})
        reader = Ext4Reader(BytesView(outer))

        iso = mount_iso(reader, "/boot/x.iso")
        assert iso.volume_id is not None or iso.label == ""
        assert iso.read_file("/inner.txt") == b"nested\n"

    def test_missing_path_raises(self):
        reader = Ext4Reader(BytesView(fsgen.build_ext4(SAMPLE)))
        with pytest.raises(FileNotFoundError):
            mount_iso(reader, "/nope.iso")

    def test_directory_raises(self):
        reader = Ext4Reader(BytesView(fsgen.build_ext4(SAMPLE)))
        with pytest.raises(IsADirectoryError):
            mount_iso(reader, "/docs")


class TestLooksLikeIso:
    @pytest.mark.parametrize("name,expected", [
        ("ubuntu.iso", True),
        ("UBUNTU.ISO", True),
        ("ubuntu.img", False),
        ("iso", False),
        ("", False),
    ])
    def test_extension_check(self, name, expected):
        assert looks_like_iso(name) is expected
