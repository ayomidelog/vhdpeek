"""The shared filesystem contract: entries, byte views, path and size helpers."""

from __future__ import annotations

import pytest

from vhdpeek.core.volume import (BytesView, Entry, ReaderView, format_size,
                                join_path, norm_path)


class TestFormatSize:
    @pytest.mark.parametrize("count,expected", [
        (0, "0 B"),
        (512, "512 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (1024 ** 2, "1.0 MiB"),
        (1024 ** 3, "1.0 GiB"),
        (1024 ** 4, "1.0 TiB"),
        (1024 ** 5, "1,024.0 TiB"),
    ])
    def test_units(self, count, expected):
        assert format_size(count) == expected


class TestPaths:
    def test_root_is_empty(self):
        assert norm_path("") == ()
        assert norm_path("/") == ()

    def test_components(self):
        assert norm_path("/etc/os-release") == ("etc", "os-release")

    def test_dot_and_repeated_separators_collapse(self):
        assert norm_path("//a/./b///c") == ("a", "b", "c")

    def test_backslashes_accepted(self):
        assert norm_path("\\docs\\manual.txt") == ("docs", "manual.txt")

    def test_join_at_root(self):
        assert join_path("", "name") == "/name"

    def test_join_nested(self):
        assert join_path("/docs", "manual.txt") == "/docs/manual.txt"

    def test_join_ignores_trailing_separator(self):
        assert join_path("/docs/", "manual.txt") == "/docs/manual.txt"


class TestBytesView:
    def test_reads_within_bounds(self):
        view = BytesView(b"abcdef")
        assert view.read(2, 3) == b"cde"

    def test_zero_fills_past_the_end(self):
        view = BytesView(b"abc")
        assert view.read(1, 5) == b"bc\x00\x00\x00"

    def test_read_past_the_end_is_all_zero(self):
        view = BytesView(b"abc")
        assert view.read(10, 2) == b"\x00\x00"

    def test_negative_offset_rejected(self):
        with pytest.raises(ValueError):
            BytesView(b"abc").read(-1, 1)


class TestReaderView:
    def test_wraps_a_callable(self):
        blob = b"0123456789"
        view = ReaderView(lambda off, size: blob[off:off + size], len(blob))
        assert view.read(3, 4) == b"3456"

    def test_clamps_past_the_end(self):
        blob = b"0123456789"
        view = ReaderView(lambda off, size: blob[off:off + size], len(blob))
        assert view.read(8, 5) == b"89\x00\x00\x00"

    def test_read_at_the_end_returns_zeros(self):
        view = ReaderView(lambda off, size: b"", 10)
        assert view.read(10, 3) == b"\x00\x00\x00"

    def test_negative_read_rejected(self):
        view = ReaderView(lambda off, size: b"", 10)
        with pytest.raises(ValueError):
            view.read(0, -1)


class TestEntry:
    def test_repr_names_the_kind(self):
        assert "dir" in repr(Entry("d", "/d", True))
        assert "file" in repr(Entry("f", "/f", False, 12))
