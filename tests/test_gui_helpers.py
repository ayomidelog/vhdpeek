"""Pure helpers in the GUI: tree ids, preview rendering, cancellation."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter", reason="GUI tests need Tk")

from vhdpeek.gui import CancelToken, make_iid, render, split_iid
from vhdpeek.gui.treeids import PLACEHOLDER


class TestEntryPointArguments:
    """
    The portable exe is a windowed build: no console, no stdout. Its argument
    handling must therefore never treat a flag as a filename.
    """

    def test_help_is_not_a_filename(self):
        from vhdpeek.gui import _take_path

        assert _take_path(["--help"]) is None
        assert _take_path(["-h"]) is None

    def test_a_path_is_taken(self):
        from vhdpeek.gui import _take_path

        assert _take_path(["disk.vhd"]) == "disk.vhd"
        assert _take_path(["--help", "disk.vhd"]) == "disk.vhd"

    def test_no_arguments(self):
        from vhdpeek.gui import _take_path

        assert _take_path([]) is None

    def test_theme_is_extracted_before_the_path(self):
        from vhdpeek.gui import _take_path, _take_theme

        args = ["--theme", "dark", "disk.vhd"]
        assert _take_theme(args) == "dark"
        assert _take_path(args) == "disk.vhd"

    def test_theme_equals_form(self):
        from vhdpeek.gui import _take_theme

        args = ["--theme=light"]
        assert _take_theme(args) == "light"
        assert args == []

    def test_unknown_theme_value_is_ignored(self):
        from vhdpeek.gui import _take_theme

        assert _take_theme(["--theme", "chartreuse"]) is None


class TestHelpers:
    def test_iid_round_trip(self):
        iid = make_iid("p3", "/etc/os-release")
        assert split_iid(iid) == ("p3", "/etc/os-release")

    def test_root_iid_round_trip(self):
        assert split_iid(make_iid("iso1", "")) == ("iso1", "")

    def test_ids_contain_no_nul(self):
        """
        Tcl truncates strings at NUL on Python <= 3.11, so an id with a NUL
        byte silently becomes its parent's id and the tree raises
        "Item ... already exists" instead of inserting a placeholder.
        """
        for iid in (make_iid("p0", ""), make_iid("p3", "/etc/os-release"),
                    make_iid("p0", "") + PLACEHOLDER):
            assert "\x00" not in iid

    def test_placeholder_id_is_distinct_from_its_parent(self):
        parent = make_iid("p0", "")
        assert parent + PLACEHOLDER != parent
        assert split_iid(parent + PLACEHOLDER)[0] == "p0"

    def test_render_text(self):
        assert render(b"hello\nworld\n") == "hello\nworld\n"

    def test_render_binary(self):
        text = render(b"\x00\x01\x02\x03")
        assert text.startswith("00000000")
        assert "00 01 02 03" in text

    def test_render_empty(self):
        assert render(b"") == "(empty file)"

    def test_render_utf8(self):
        assert "café" in render("café".encode("utf-8"))

    def test_cancel_token(self):
        token = CancelToken()
        assert not token.cancelled
        token.cancel()
        assert token.cancelled
