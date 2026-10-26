"""Pure helpers in the GUI: tree ids, preview rendering, cancellation."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter", reason="GUI tests need Tk")

from vhdpeek.gui import CancelToken, make_iid, render, split_iid


class TestHelpers:
    def test_iid_round_trip(self):
        iid = make_iid("p3", "/etc/os-release")
        assert split_iid(iid) == ("p3", "/etc/os-release")

    def test_root_iid_round_trip(self):
        assert split_iid(make_iid("iso1", "")) == ("iso1", "")

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
