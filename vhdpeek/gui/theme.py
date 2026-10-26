"""
Light and dark palettes, and the ttk configuration that applies them.

Tk splits into two widget families that theme in completely different ways:

  * ttk widgets take their colours from a named ttk theme, and the *native*
    themes ("vista" on Windows, "aqua" on macOS) ignore colour configuration
    entirely. A dark palette therefore means switching to "clam", the most
    configurable theme that ships with Tk.
  * classic widgets (`tk.Text`, `tk.Toplevel`) take colours directly.

So a palette is applied in two places: `configure_style` for ttk, and
`recolor_text` for the one classic widget the app owns.

The preference is remembered, because a theme toggle that resets on restart is
worse than no toggle.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Optional, Tuple


@dataclass(frozen=True)
class Palette:
    """Every colour the window uses. No widget may hardcode one."""

    name: str
    bg: str            # window background
    surface: str       # raised surfaces: entry fields, tree body
    fg: str            # primary text
    muted: str         # hints and secondary text
    border: str        # separators and outlines
    accent: str        # selection and progress
    on_accent: str     # text drawn on the accent colour
    error: str
    warning: str

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"


LIGHT = Palette(
    name="light",
    bg="#f3f3f3",
    surface="#ffffff",
    fg="#1a1a1a",
    muted="#666666",
    border="#c8c8c8",
    accent="#0067c0",
    on_accent="#ffffff",
    error="#b00020",
    warning="#8a6d00",
)

DARK = Palette(
    name="dark",
    bg="#1e1e1e",
    surface="#252526",
    fg="#e8e8e8",
    muted="#9d9d9d",
    border="#3c3c3c",
    accent="#0a84ff",
    on_accent="#ffffff",
    error="#f48771",
    warning="#e2c08d",
)

_BY_NAME = {palette.name: palette for palette in (LIGHT, DARK)}

#: Preferred families, best first, for the monospaced label and preview.
_MONO = ("Consolas", "Cascadia Mono", "Menlo", "SF Mono", "DejaVu Sans Mono",
         "Liberation Mono", "Courier New")


def palette_for(dark: bool) -> Palette:
    return DARK if dark else LIGHT


def palette_named(name: str) -> Palette:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown palette {name!r}") from None


def mono_font(widget: tk.Misc, size: int = 9) -> Tuple[str, int]:
    """
    A monospaced family that actually exists on this platform.

    "Consolas" is Windows-only; without this the preview falls back to a
    proportional font on macOS and Linux and the hex dump stops lining up.
    """
    try:
        available = set(tkfont.families(widget))
    except Exception:
        available = set()
    for family in _MONO:
        if family in available:
            return (family, size)
    return ("Courier", size)


# ---------------------------------------------------------------------------
# System preference
# ---------------------------------------------------------------------------

_WIN_PERSONALIZE = (r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Themes\Personalize")


def system_prefers_dark() -> bool:
    """The desktop's own preference, or False when it cannot be determined."""
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                _WIN_PERSONALIZE) as key:
                light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return light == 0

        if sys.platform == "darwin":
            done = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2)
            return done.stdout.strip().lower() == "dark"

        done = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface",
             "color-scheme"],
            capture_output=True, text=True, timeout=2)
        return "dark" in done.stdout.lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Remembered preference
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    override = os.environ.get("VHDPEEK_CONFIG_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "vhdpeek" / "ui.conf"


def load_preference() -> Optional[bool]:
    """The theme the user chose last time, or None if they never chose."""
    try:
        text = _config_path().read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    if text == "dark":
        return True
    if text == "light":
        return False
    return None


def save_preference(dark: bool) -> None:
    path = _config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dark\n" if dark else "light\n", encoding="utf-8")
    except OSError:
        pass        # a read-only config directory must not break the window


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def configure_style(style: ttk.Style, palette: Palette,
                    widget: Optional[tk.Misc] = None) -> None:
    """Recolour every ttk style the window uses."""
    names = style.theme_names()
    if palette.is_dark:
        if "clam" in names:
            style.theme_use("clam")
    else:
        # Back to the platform look when the palette allows it.
        for preferred in ("vista", "aqua", "clam"):
            if preferred in names:
                style.theme_use(preferred)
                break

    bg, surface = palette.bg, palette.surface
    fg, border = palette.fg, palette.border
    mono = mono_font(widget or style.master)

    style.configure(".", background=bg, foreground=fg,
                    fieldbackground=surface, bordercolor=border,
                    focuscolor=palette.accent,
                    selectbackground=palette.accent,
                    selectforeground=palette.on_accent)

    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Mono.TLabel", background=bg, foreground=fg, font=mono)
    style.configure("Muted.TLabel", background=bg, foreground=palette.muted)

    style.configure("TButton", background=surface, foreground=fg,
                    bordercolor=border, padding=(10, 4))
    style.map("TButton",
              background=[("pressed", palette.accent),
                          ("active", border)],
              foreground=[("pressed", palette.on_accent)])

    style.configure("TEntry", fieldbackground=surface, foreground=fg,
                    bordercolor=border, insertcolor=fg)
    style.map("TEntry", bordercolor=[("focus", palette.accent)])

    style.configure("TSeparator", background=border)
    style.configure("TPanedwindow", background=bg)

    style.configure("TScrollbar", background=surface, troughcolor=bg,
                    bordercolor=border, arrowcolor=fg)
    style.map("TScrollbar", background=[("active", border)])

    style.configure("TProgressbar", background=palette.accent,
                    troughcolor=surface, bordercolor=border)

    style.configure("Treeview", background=surface, fieldbackground=surface,
                    foreground=fg, bordercolor=border)
    style.map("Treeview",
              background=[("selected", palette.accent)],
              foreground=[("selected", palette.on_accent)])
    style.configure("Treeview.Heading", background=bg, foreground=fg,
                    bordercolor=border, relief="flat")
    style.map("Treeview.Heading", background=[("active", surface)])


def recolor_text(widget: tk.Text, palette: Palette) -> None:
    """Recolour the preview, which is a classic widget and ignores ttk."""
    widget.configure(background=palette.surface, foreground=palette.fg,
                     insertbackground=palette.fg,
                     selectbackground=palette.accent,
                     selectforeground=palette.on_accent,
                     highlightbackground=palette.border,
                     highlightcolor=palette.accent)


def recolor_window(window: tk.Misc, palette: Palette) -> None:
    """Recolour a Toplevel's own background (dialogs, not frames)."""
    window.configure(background=palette.bg)
