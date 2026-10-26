"""
The window: toolbar, tree, preview, status bar, and open/refresh.

Layout only. Tree behaviour lives in `tree.py`, copy-out in `copy.py`,
preview rendering in `preview.py`.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Optional

from ..core.volume import format_size
from ..session import ImageInfo, Session
from .background import Background
from .copy import CopyMixin
from .tree import TreeMixin


class App(TreeMixin, CopyMixin):
    def __init__(self, root: tk.Tk, initial: Optional[str] = None) -> None:
        self.root = root
        self.session = Session()
        self.background = Background(root)
        self.background._on_progress = self._show_progress
        self.background._on_error = self._show_error
        self.background._on_cancelled = lambda: self._status("Cancelled")

        self._selected: Optional[str] = None
        self._token = None
        self._suppress_select = False

        root.title("vhdpeek")
        root.geometry("1120x720")
        root.minsize(780, 440)

        self._build()
        self._bind_keys()

        if initial:
            self.open_path(initial)
        else:
            self._status("Open a VHD/VHDX image, or a URL, to begin.")

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Mono.TLabel", font=("Consolas", 9))

        self._build_toolbar()
        self._build_body()
        self._build_status()

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(10, 8, 10, 6))
        toolbar.pack(side="top", fill="x")

        ttk.Button(toolbar, text="Open image…",
                   command=self.choose_file).pack(side="left")
        ttk.Button(toolbar, text="Open URL…",
                   command=self.ask_url).pack(side="left", padx=(6, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", padx=10,
                                                      fill="y")
        ttk.Button(toolbar, text="Copy out…",
                   command=self.copy_out).pack(side="left")
        ttk.Button(toolbar, text="Refresh",
                   command=self.refresh).pack(side="left", padx=(6, 0))

        self.info_label = ttk.Label(toolbar, text="", style="Mono.TLabel")
        self.info_label.pack(side="right")

    def _build_body(self) -> None:
        body = ttk.Panedwindow(self.root, orient="vertical")
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 6))

        upper = ttk.Frame(body)
        header = ttk.Frame(upper)
        header.pack(fill="x")
        self.location = ttk.Label(header, text="", style="Mono.TLabel")
        self.location.pack(side="left")

        self.tree = ttk.Treeview(upper, columns=("size", "type"),
                                 show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Image contents", anchor="w")
        self.tree.heading("size", text="Size", anchor="e")
        self.tree.heading("type", text="Type", anchor="w")
        self.tree.column("#0", width=520, minwidth=240, stretch=True)
        self.tree.column("size", width=100, stretch=True, anchor="e")
        self.tree.column("type", width=110, stretch=True)

        yscroll = ttk.Scrollbar(upper, orient="vertical",
                                command=self.tree.yview)
        xscroll = ttk.Scrollbar(upper, orient="horizontal",
                                command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set,
                            xscrollcommand=xscroll.set)
        xscroll.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewOpen>>", self._node_opened)
        self.tree.bind("<<TreeviewSelect>>", self._node_selected)
        self.tree.bind("<Double-1>", self._node_activated)
        body.add(upper, weight=3)

        preview_frame = ttk.Frame(body)
        ttk.Label(preview_frame, text="Preview").pack(anchor="w")
        self.preview = tk.Text(preview_frame, wrap="none", height=9,
                               font=("Consolas", 9), state="disabled",
                               background="#fbfbfb", relief="solid",
                               borderwidth=1)
        preview_scroll = ttk.Scrollbar(preview_frame, orient="vertical",
                                       command=self.preview.yview)
        self.preview.configure(yscrollcommand=preview_scroll.set)
        self.preview.pack(side="left", fill="both", expand=True)
        preview_scroll.pack(side="right", fill="y")
        body.add(preview_frame, weight=2)

    def _build_status(self) -> None:
        status = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        status.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(status, mode="determinate", length=190)
        self.progress.pack(side="right")
        self.status_label = ttk.Label(status, text="")
        self.status_label.pack(side="left", fill="x", expand=True)

    def _bind_keys(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self.choose_file())
        self.root.bind("<Control-u>", lambda _e: self.ask_url())
        self.root.bind("<Control-e>", lambda _e: self.copy_out())
        self.root.bind("<F5>", lambda _e: self.refresh())
        self.root.bind("<Escape>", lambda _e: self.cancel())

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _show_error(self, exc: BaseException) -> None:
        self._idle()
        self._status(f"{type(exc).__name__}: {exc}")

    def _show_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        self.progress.configure(mode="determinate", maximum=total, value=done)
        self._status(f"{format_size(done)} of {format_size(total)}  "
                     f"({done * 100 // total}%)")

    def _busy(self, message: str) -> None:
        self._status(message)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

    def _idle(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)

    # ------------------------------------------------------------------
    # Opening
    # ------------------------------------------------------------------

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open a VHD or VHDX image",
            filetypes=[("Disk images", "*.vhd *.vhdx"), ("All files", "*.*")],
        )
        if path:
            self.open_path(path)

    def ask_url(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Open image from URL")
        dialog.transient(self.root)
        dialog.resizable(True, False)

        ttk.Label(dialog, text="URL (http or https):").pack(
            anchor="w", padx=12, pady=(12, 4))
        entry = ttk.Entry(dialog, width=78)
        entry.pack(fill="x", padx=12)
        entry.focus_set()
        ttk.Label(dialog, style="Mono.TLabel", foreground="#666",
                  text="Only the metadata is fetched, not the image."
                  ).pack(anchor="w", padx=12, pady=(4, 0))

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=12)

        def accept() -> None:
            url = entry.get().strip()
            if url:
                dialog.destroy()
                self.open_path(url)

        ttk.Button(buttons, text="Open", command=accept).pack(side="right")
        ttk.Button(buttons, text="Cancel",
                   command=dialog.destroy).pack(side="right", padx=(0, 6))
        entry.bind("<Return>", lambda _e: accept())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    def open_path(self, path_or_url: str) -> None:
        if self.background.busy:
            self._status("Busy; wait for the current operation.")
            return
        self._busy(f"Opening {os.path.basename(path_or_url)}…")
        session = self.session

        def work() -> ImageInfo:
            return session.open(path_or_url)

        def done(info: ImageInfo) -> None:
            self._idle()
            self.info_label.configure(text=info.summary)
            self.root.title(f"vhdpeek — {os.path.basename(info.path)}")
            self._populate()
            if info.is_dirty:
                self._status("Warning: the VHDX log is not empty; the image "
                             "was not closed cleanly and reads may be stale.")
            elif info.parent_name:
                self._status(f"Differencing disk; parent {info.parent_name} "
                             f"is not resolved, so parent-backed blocks read "
                             f"as zeros.")
            else:
                self._status(f"{len(session.volumes)} partition(s). "
                             f"Expand one to browse it.")

        self.background.submit(work, done)

    def refresh(self) -> None:
        if self.session.image is None:
            return
        self.open_path(self.session.image.path)
