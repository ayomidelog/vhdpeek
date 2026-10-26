"""Theming, and where dialogs are placed."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter", reason="GUI tests need Tk")

from vhdpeek.gui import theme
from vhdpeek.gui.urldialog import centered_position


class TestCenteredPosition:
    def test_centres_horizontally(self):
        x, _y = centered_position((0, 0, 1000, 800), (400, 200))
        assert x == 300

    def test_sits_above_vertical_centre(self):
        _x, y = centered_position((0, 0, 1000, 800), (400, 200))
        assert y < (800 - 200) // 2

    def test_accounts_for_the_parent_origin(self):
        """A window at (500, 300) centres its dialog there, not at 0,0."""
        x, y = centered_position((500, 300, 1000, 800), (400, 200))
        assert (x, y) == (800, 500)

    def test_odd_difference_does_not_produce_a_fraction(self):
        x, y = centered_position((0, 0, 999, 799), (400, 201))
        assert isinstance(x, int) and isinstance(y, int)

    def test_clamped_to_the_left_edge(self):
        x, _y = centered_position((-400, 0, 300, 800), (640, 200),
                                  screen=(1920, 1080))
        assert x == 0

    def test_clamped_to_the_right_edge(self):
        x, _y = centered_position((1800, 0, 1000, 800), (640, 200),
                                  screen=(1920, 1080))
        assert x == 1920 - 640

    def test_clamped_to_the_top_edge(self):
        _x, y = centered_position((0, -500, 1000, 800), (400, 200),
                                  screen=(1920, 1080))
        assert y == 0

    def test_clamped_to_the_bottom_edge(self):
        _x, y = centered_position((0, 1000, 1000, 800), (400, 200),
                                  screen=(1920, 1080))
        assert y == 1080 - 200

    def test_a_dialog_larger_than_the_screen_still_starts_inside(self):
        x, y = centered_position((0, 0, 100, 100), (3000, 2000),
                                 screen=(1920, 1080))
        assert x == 0 and y == 0


class TestPalette:
    def test_named_lookup(self):
        assert theme.palette_named("dark").is_dark
        assert not theme.palette_named("light").is_dark

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError):
            theme.palette_named("solarized")

    def test_dark_is_actually_dark(self):
        dark = theme.palette_for(True)
        assert dark.bg != dark.fg
        assert int(dark.bg[1:3], 16) < 0x40

    def test_light_is_actually_light(self):
        light = theme.palette_for(False)
        assert int(light.bg[1:3], 16) > 0xC0

    def test_text_contrasts_with_its_background(self):
        def luminance(colour: str) -> float:
            r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for palette in (theme.LIGHT, theme.DARK):
            for surface in (palette.bg, palette.surface):
                assert abs(luminance(surface) - luminance(palette.fg)) > 0.4, \
                    f"{palette.name}: fg is unreadable on {surface}"

    def test_every_palette_defines_every_colour(self):
        for palette in (theme.LIGHT, theme.DARK):
            for field in ("bg", "surface", "fg", "muted", "border", "accent",
                          "on_accent", "error", "warning"):
                value = getattr(palette, field)
                assert value.startswith("#") and len(value) == 7, field


class TestPreference:
    def test_saved_preference_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VHDPEEK_CONFIG_DIR", str(tmp_path))
        theme.save_preference(True)
        assert theme.load_preference() is True
        theme.save_preference(False)
        assert theme.load_preference() is False

    def test_no_preference_reads_as_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VHDPEEK_CONFIG_DIR", str(tmp_path))
        assert theme.load_preference() is None

    def test_corrupt_preference_reads_as_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VHDPEEK_CONFIG_DIR", str(tmp_path))
        path = tmp_path / "vhdpeek" / "ui.conf"
        path.parent.mkdir(parents=True)
        path.write_text("chartreuse\n", encoding="utf-8")
        assert theme.load_preference() is None

    def test_unwritable_directory_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VHDPEEK_CONFIG_DIR", str(tmp_path / "nope"))
        monkeypatch.setattr(theme.Path, "mkdir",
                            lambda *a, **k: (_ for _ in ()).throw(OSError()))
        theme.save_preference(True)          # must not raise


class TestSystemPreference:
    def test_returns_a_bool_and_never_raises(self):
        assert isinstance(theme.system_prefers_dark(), bool)


class TestUrlDialog:
    def test_dialog_is_placed_over_the_parent(self, app):
        """
        Tk defaults to the top-left of the screen. An unmapped window reports
        rootx/rooty as 0, so the requested geometry is what has to be checked.
        """
        import re

        from vhdpeek.gui import urldialog

        app.root.geometry("900x600+300+200")
        app.root.update_idletasks()

        prompt = urldialog.ask(app.root, app.palette, lambda _url: None)
        try:
            app.root.update_idletasks()
            match = re.search(r"\+(\d+)\+(\d+)$", prompt.window.geometry())
            assert match, prompt.window.geometry()
            x, y = int(match.group(1)), int(match.group(2))

            expected = urldialog.centered_position(
                (app.root.winfo_rootx(), app.root.winfo_rooty(),
                 app.root.winfo_width(), app.root.winfo_height()),
                (prompt.window.winfo_reqwidth(),
                 prompt.window.winfo_reqheight()),
                (prompt.window.winfo_screenwidth(),
                 prompt.window.winfo_screenheight()),
            )
            assert (x, y) == expected
            assert (x, y) != (0, 0)
            # Over the parent, not somewhere else on the desktop.
            assert app.root.winfo_rootx() <= x
            assert app.root.winfo_rooty() <= y
        finally:
            prompt.cancel()

    def test_moving_the_parent_moves_the_dialog(self, app):
        import re

        from vhdpeek.gui import urldialog

        def position() -> tuple:
            prompt = urldialog.ask(app.root, app.palette, lambda _url: None)
            app.root.update_idletasks()
            match = re.search(r"\+(\d+)\+(\d+)$", prompt.window.geometry())
            prompt.cancel()
            return int(match.group(1)), int(match.group(2))

        app.root.geometry("900x600+100+100")
        app.root.update_idletasks()
        first = position()

        app.root.geometry("900x600+600+400")
        app.root.update_idletasks()
        second = position()

        assert second[0] > first[0]
        assert second[1] > first[1]

    def test_accept_reports_the_url(self, app):
        from vhdpeek.gui import urldialog

        opened = []
        prompt = urldialog.ask(app.root, app.palette, opened.append)
        prompt.entry.insert(0, "https://example.com/disk.vhd")
        prompt.accept()

        assert opened == ["https://example.com/disk.vhd"]
        assert not prompt.open

    def test_url_is_trimmed(self, app):
        from vhdpeek.gui import urldialog

        opened = []
        prompt = urldialog.ask(app.root, app.palette, opened.append)
        prompt.entry.insert(0, "  https://example.com/a.vhdx  ")
        prompt.accept()
        assert opened == ["https://example.com/a.vhdx"]

    def test_empty_url_is_ignored_and_the_box_stays_open(self, app):
        from vhdpeek.gui import urldialog

        opened = []
        prompt = urldialog.ask(app.root, app.palette, opened.append)
        prompt.entry.insert(0, "   ")
        prompt.accept()
        try:
            assert prompt.open
        finally:
            prompt.cancel()
        assert opened == []

    def test_cancel_closes_without_reporting(self, app):
        from vhdpeek.gui import urldialog

        opened = []
        prompt = urldialog.ask(app.root, app.palette, opened.append)
        prompt.cancel()
        assert not prompt.open
        assert opened == []

    def test_enter_and_escape_are_bound(self, app):
        from vhdpeek.gui import urldialog

        prompt = urldialog.ask(app.root, app.palette, lambda _url: None)
        try:
            assert prompt.entry.bind("<Return>")
            assert prompt.window.bind("<Escape>")
        finally:
            prompt.cancel()


class TestAppliedToARealWindow:
    """The palette has to reach the widgets, not just exist."""

    def test_app_starts_in_a_consistent_palette(self, app):
        assert app.palette.name in ("dark", "light")
        assert app.preview.cget("background") == app.palette.surface
        assert app.preview.cget("foreground") == app.palette.fg

    def test_toggle_repaints_and_persists(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("VHDPEEK_CONFIG_DIR", str(tmp_path))
        before = app.palette.name

        app.toggle_theme()

        assert app.palette.name != before
        assert app.preview.cget("background") == app.palette.surface
        assert app.preview.cget("foreground") == app.palette.fg
        assert theme.load_preference() is app.dark
        assert "theme" in app.status_label.cget("text").lower()

    def test_toggling_twice_returns_to_the_start(self, app, tmp_path,
                                                monkeypatch):
        monkeypatch.setenv("VHDPEEK_CONFIG_DIR", str(tmp_path))
        before = app.palette.name
        app.toggle_theme()
        app.toggle_theme()
        assert app.palette.name == before

    def test_tree_keeps_working_after_a_toggle(self, app, gui_images):
        from tests.gui_support import listed, open_and_wait, pump
        from vhdpeek.gui import make_iid

        open_and_wait(app, gui_images["ext4"])
        root_iid = make_iid("p0", "")
        pump(app, lambda: listed(app, root_iid))

        app.toggle_theme()

        assert app.tree.exists(root_iid)
        assert app.tree.get_children(root_iid)
