"""
vhdpeek GUI — explore a VHD/VHDX image without downloading or mounting it.

    python -m vhdpeek --gui [image-or-url] [--theme dark|light]

Nothing here parses anything: that all lives in `session.Session`.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import List, Optional

from . import theme
from .app import App
from .background import Background, CancelToken, Cancelled
from .preview import render
from .treeids import make_iid, split_iid
from .urldialog import centered_position

__all__ = [
    "App",
    "Background",
    "CancelToken",
    "Cancelled",
    "make_iid",
    "split_iid",
    "render",
    "centered_position",
    "theme",
    "main",
]


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    chosen = _take_theme(args)
    initial = args[0] if args else None

    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass

    app = App(root, initial)
    if chosen is not None:
        app.dark = chosen == "dark"
        app.apply_theme()

    def on_close() -> None:
        app.background.shutdown()
        app.session.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


def _take_theme(args: List[str]) -> Optional[str]:
    """Strip `--theme dark|light` out of `args`, returning the value."""
    for index, arg in enumerate(args):
        if arg == "--theme" and index + 1 < len(args):
            value = args[index + 1].lower()
            del args[index:index + 2]
            if value in ("dark", "light"):
                return value
            return None
        if arg.startswith("--theme="):
            value = arg.split("=", 1)[1].lower()
            del args[index]
            if value in ("dark", "light"):
                return value
            return None
    return None


if __name__ == "__main__":
    sys.exit(main())
