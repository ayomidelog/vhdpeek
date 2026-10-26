"""
The "Open URL" prompt.

Tk hands a new Toplevel to the window manager, which on Windows places it in
the top-left corner of the screen regardless of where the app is. A prompt
belongs over the window that raised it, so the position is computed here and
set explicitly.

The window and its two actions are exposed as a small object rather than a
bare Toplevel, so the behaviour can be driven without synthesising key events
(a withdrawn window does not reliably deliver them).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, Tuple

from . import theme

#: Vertically, a prompt sits a little above centre: the eye starts there.
_VERTICAL_BIAS = 3


def centered_position(parent: Tuple[int, int, int, int],
                      size: Tuple[int, int],
                      screen: Optional[Tuple[int, int]] = None
                      ) -> Tuple[int, int]:
    """
    Top-left corner that centres `size` over `parent`.

    `parent` is (x, y, width, height) in screen coordinates. When `screen` is
    given the result is clamped to it, so a prompt for a window near an edge
    stays fully visible.
    """
    parent_x, parent_y, parent_w, parent_h = parent
    width, height = size

    x = parent_x + (parent_w - width) // 2
    y = parent_y + (parent_h - height) // _VERTICAL_BIAS

    if screen is not None:
        screen_w, screen_h = screen
        x = max(0, min(x, screen_w - width))
        y = max(0, min(y, screen_h - height))
    return x, y


def center_on(parent: tk.Misc, window: tk.Toplevel) -> None:
    """Place `window` centred over `parent`, once both know their size."""
    window.update_idletasks()
    parent.update_idletasks()
    x, y = centered_position(
        (parent.winfo_rootx(), parent.winfo_rooty(),
         parent.winfo_width(), parent.winfo_height()),
        (window.winfo_reqwidth(), window.winfo_reqheight()),
        (window.winfo_screenwidth(), window.winfo_screenheight()),
    )
    window.geometry(f"+{x}+{y}")


class UrlPrompt:
    """A URL entry box, centred over its parent."""

    def __init__(self, parent: tk.Misc, palette: theme.Palette,
                 on_open: Callable[[str], None]):
        self.on_open = on_open

        self.window = tk.Toplevel(parent)
        self.window.title("Open image from URL")
        self.window.transient(parent)
        theme.recolor_window(self.window, palette)

        body = ttk.Frame(self.window, padding=(14, 12, 14, 12))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="URL (http or https):").pack(anchor="w")
        self.entry = ttk.Entry(body, width=76)
        self.entry.pack(fill="x", pady=(4, 0))

        ttk.Label(body, style="Muted.TLabel",
                  text="Only the metadata is fetched, not the image."
                  ).pack(anchor="w", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Open", command=self.accept).pack(side="right")
        ttk.Button(buttons, text="Cancel",
                   command=self.cancel).pack(side="right", padx=(0, 6))

        self.entry.bind("<Return>", lambda _event: self.accept())
        self.window.bind("<Escape>", lambda _event: self.cancel())

        center_on(parent, self.window)
        self.entry.focus_set()

    def accept(self) -> None:
        """Hand the URL over and close. An empty box just stays open."""
        url = self.entry.get().strip()
        if not url:
            return
        self.window.destroy()
        self.on_open(url)

    def cancel(self) -> None:
        self.window.destroy()

    @property
    def open(self) -> bool:
        return bool(self.window.winfo_exists())


def ask(parent: tk.Misc, palette: theme.Palette,
        on_open: Callable[[str], None]) -> UrlPrompt:
    """
    Show the prompt. `on_open` is called with the URL, then the dialog closes.

    Not modal: the caller keeps control, and there is no nested event loop to
    escape from if the window is closed underneath it.
    """
    return UrlPrompt(parent, palette, on_open)
