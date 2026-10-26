"""Container detection: what each rejection says, and where it looks."""

from __future__ import annotations

import pytest

from vhdpeek.core.containers import detect_and_parse
from vhdpeek.core.volume import BytesView
from vhdpeek.core.containers.vhd import bitmap_size
from vhdpeek.core.containers.vhdx import guid_string
from vhdpeek.core.source import Source

from tests.fixtures import fsgen, vhdgen

SAMPLE = {"a.txt": b"a\n"}


class NoSize(Source):
    """A source that cannot report its own length."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self, offset: int, size: int) -> bytes:
        return self._data[offset:offset + size]

    @property
    def size(self):
        return None


def disk_bytes() -> bytes:
    return vhdgen.assemble_disk(fsgen.build_fat32(SAMPLE), "mbr", 1)


class TestDetection:
    def test_fixed_vhd(self):
        info = detect_and_parse(BytesView(vhdgen.wrap_fixed_vhd(disk_bytes())))
        assert info.disk_type == "fixed"
        assert info.virtual_size == len(disk_bytes())

    def test_dynamic_vhd(self):
        info = detect_and_parse(BytesView(vhdgen.wrap_dynamic_vhd(disk_bytes())))
        assert info.disk_type == "dynamic"
        assert info.bat_entries > 0

    def test_vhdx(self):
        info = detect_and_parse(BytesView(vhdgen.wrap_vhdx(disk_bytes())))
        assert info.disk_type == "vhdx"
        assert info.bat_entry_size == 8
        assert info.bat_little_endian

    def test_unknown_size_is_reported_not_guessed(self):
        with pytest.raises(ValueError, match="cannot determine image size"):
            detect_and_parse(NoSize(b"\x00" * 2048))

    def test_tiny_file_is_rejected(self):
        with pytest.raises(ValueError, match="too small"):
            detect_and_parse(BytesView(b"\x00" * 100))

    def test_random_bytes_are_rejected(self):
        with pytest.raises(ValueError, match="not a recognised"):
            detect_and_parse(BytesView(b"\x00" * 4096))

    def test_vhdx_magic_without_regions_is_rejected(self):
        blob = b"vhdxfile" + b"\x00" * (512 << 10)
        with pytest.raises(ValueError, match="region table"):
            detect_and_parse(BytesView(vhdgen.wrap_fixed_vhd(blob)))


class TestVhdxHelpers:
    def test_guid_is_canonical(self):
        raw = bytes.fromhex("6677c22d23f600429d64115e9bfd4a08")
        assert guid_string(raw) == "2DC27766-F623-4200-9D64-115E9BFD4A08"


class TestVhdHelpers:
    @pytest.mark.parametrize("block_size,expected", [
        (512, 512),
        (2 << 20, 512),
        (1 << 20, 512),
    ])
    def test_bitmap_covers_every_sector_and_rounds_to_a_sector(self,
                                                             block_size,
                                                             expected):
        assert bitmap_size(block_size) == expected
        assert expected % 512 == 0
