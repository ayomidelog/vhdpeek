"""
vhdpeek GUI — explore a VHD/VHDX image without downloading or mounting it.

    python -m vhdpeek.gui [image-or-url]
    python -m vhdpeek --gui [image-or-url]

Nothing here parses anything: that all lives in `session.Session`.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import List, Optional

from .app import App
from .background import Background, CancelToken, Cancelled
from .preview import render
from .treeids import make_iid, split_iid

__all__ = [
    "App",
    "Background",
    "CancelToken",
    "Cancelled",
    "make_iid",
    "split_iid",
    "render",
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
    initial = args[0] if args else None

    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass

    app = App(root, initial)

    def on_close() -> None:
        app.background.shutdown()
        app.session.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
