"""
One worker thread, so filesystem calls never block the Tk event loop.

A remote image costs ~100 ms per round trip; touching a reader from the Tk
thread would freeze the window. A single worker also means a reader is never
used from two threads at once.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

POLL_MS = 40


class Cancelled(Exception):
    """Raised inside a worker when the user cancels."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class Background:
    """One worker thread; results are delivered on the Tk thread."""

    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="vhdpeek")
        self._busy = False
        self._closed = False
        self._root.after(POLL_MS, self._drain)

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, work: Callable[[], object],
               success: Callable[[object], None],
               error: Optional[Callable[[BaseException], None]] = None
               ) -> None:
        self._busy = True

        def run() -> None:
            try:
                result = work()
            except Cancelled:
                self._queue.put(("cancelled", None, None))
            except BaseException as exc:  # surfaced on the UI thread
                self._queue.put(("error", exc, error))
            else:
                self._queue.put(("ok", result, success))

        self._pool.submit(run)

    def report(self, done: int, total: int) -> None:
        """Called from the worker; never touches Tk."""
        self._queue.put(("progress", (done, total), None))

    def shutdown(self) -> None:
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _drain(self) -> None:
        try:
            while True:
                kind, payload, callback = self._queue.get_nowait()
                if kind == "progress":
                    done, total = payload
                    self._on_progress(done, total)
                    continue
                self._busy = False
                if kind == "ok" and callback:
                    callback(payload)
                elif kind == "error" and callback:
                    callback(payload)
                elif kind == "error":
                    self._on_error(payload)
                elif kind == "cancelled":
                    self._on_cancelled()
        except queue.Empty:
            pass
        if self._closed:
            return
        try:
            self._root.after(POLL_MS, self._drain)
        except tk.TclError:
            pass

    # Replaced by the app.
    def _on_progress(self, done: int, total: int) -> None:
        pass

    def _on_error(self, exc: BaseException) -> None:
        pass

    def _on_cancelled(self) -> None:
        pass
