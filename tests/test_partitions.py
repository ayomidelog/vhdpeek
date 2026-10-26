"""Partition table tests: MBR, GPT and the extended partition chain."""

from __future__ import annotations

import pytest

from vhdpeek.core.containers import detect_and_parse
from vhdpeek.core.partitions import Partition, parse_partitions
from vhdpeek.core.volume import BytesView

from tests.fixtures import vhdgen
from tests.support import images, open_disk  # noqa: F401

__all__ = ["images"]


def table_for(disk: bytes):
    """Parse the partition table of a raw fixed-VHD image."""
    return parse_partitions(detect_and_parse(BytesView(disk)))


class TestPartitions:
    @pytest.mark.parametrize("kind", ["fixed", "dynamic", "vhdx"])
    def test_mbr(self, images, kind):
        parts = parse_partitions(open_disk(images["containers"][kind]))
        assert len(parts) == 1
        assert parts[0].scheme == "mbr"
        assert parts[0].start_lba == 1
        assert parts[0].size_bytes > 0

    def test_gpt(self, images):
        parts = parse_partitions(open_disk(images["containers"]["gpt_ext4"]))
        assert len(parts) == 1
        assert parts[0].scheme == "gpt"
        assert parts[0].start_lba == 2048
        assert parts[0].name == "root"
        assert parts[0].type_guid.startswith("0FC63DAF")

    def test_extended_partition_chain(self):
        disk = bytearray(8192 * 512)
        disk[0:512] = vhdgen.build_mbr([(2048, 2048, 0x05, "ext")])
        disk[2048 * 512:2049 * 512] = vhdgen.build_ebr(1, 1000, 0x83, 1100)
        disk[3148 * 512:3149 * 512] = vhdgen.build_ebr(1, 500, 0x83, None)

        parts = table_for(vhdgen.wrap_fixed_vhd(bytes(disk)))
        assert [p.index for p in parts] == [4, 5]
        assert parts[0].start_lba == 2049
        assert parts[1].start_lba == 3149
        assert parts[1].size_bytes == 500 * 512

    def test_extended_chain_does_not_repeat_itself(self):
        """A link pointing back at its own EBR must terminate."""
        disk = bytearray(8192 * 512)
        disk[0:512] = vhdgen.build_mbr([(2048, 2048, 0x05, "ext")])
        disk[2048 * 512:2049 * 512] = vhdgen.build_ebr(1, 100, 0x83, 0)

        parts = table_for(vhdgen.wrap_fixed_vhd(bytes(disk)))
        assert len(parts) == 1

    def test_blank_disk_has_no_partitions(self):
        assert table_for(vhdgen.wrap_fixed_vhd(b"\x00" * (2048 * 512))) == []

    def test_sector_without_boot_signature_is_not_a_table(self):
        disk = bytearray(2048 * 512)
        disk[0:64] = b"\xAA" * 64          # no 0x55AA at 510
        assert table_for(vhdgen.wrap_fixed_vhd(bytes(disk))) == []


class TestPartitionArithmetic:
    def test_size_and_offset(self):
        part = Partition(index=0, start_lba=2048, end_lba=4095,
                         type="0x83", sector_size=512)
        assert part.size_bytes == (4095 - 2048 + 1) * 512
        assert part.start_offset == 2048 * 512

    def test_sector_size_is_honoured(self):
        part = Partition(index=0, start_lba=256, end_lba=511,
                         type="0x83", sector_size=4096)
        assert part.size_bytes == 256 * 4096
        assert part.start_offset == 256 * 4096

    def test_single_sector_partition(self):
        part = Partition(index=0, start_lba=10, end_lba=10, type="0x83")
        assert part.size_bytes == 512

    def test_repr_includes_name_when_present(self):
        named = Partition(index=2, start_lba=1, end_lba=2, type="Linux",
                          name="root")
        assert "root" in repr(named)
        assert "root" not in repr(Partition(index=2, start_lba=1, end_lba=2,
                                           type="Linux"))
