"""
Copy-out: files streamed to a save path, folders copied recursively.

A folder copy walks the tree first to size the job, so the progress bar is
byte-accurate rather than "some files".
"""

from __future__ import annotations

import os
from tkinter import filedialog
from typing import Tuple

from ..core.volume import Entry, format_size
from .background import CancelToken, Cancelled
from .treeids import split_iid

COPY_CHUNK = 256 * 1024


class CopyMixin:
    """Mixed into `App`; expects `self.session`, `self.background`, `self._selected`."""

    def copy_out(self) -> None:
        node = self._selected
        if not node:
            self._status("Select a file or folder to copy out.")
            return
        scope_id, path = split_iid(node)
        if not path:
            self._status("Select a file or folder inside a partition.")
            return

        try:
            entry = self.session.stat(scope_id, path)
        except Exception as exc:
            self._status(f"Cannot read {path}: {exc}")
            return
        if entry is None:
            self._status("Nothing selected.")
            return

        if entry.is_dir:
            self._copy_directory(scope_id, path, entry)
        else:
            self._copy_file(scope_id, path, entry)

    def _copy_file(self, scope_id: str, path: str, entry: Entry) -> None:
        destination = filedialog.asksaveasfilename(
            title="Copy file out", initialfile=entry.name)
        if not destination:
            return

        token = CancelToken()
        self._token = token
        session = self.session
        background = self.background

        def work() -> int:
            read = session.file_reader(scope_id, path)
            total = entry.size
            done = 0
            with open(destination, "wb") as handle:
                while done < total:
                    if token.cancelled:
                        raise Cancelled()
                    chunk = read(done, min(COPY_CHUNK, total - done))
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    background.report(done, total)
            return done

        def done(written: int) -> None:
            self._idle()
            self._token = None
            self._status(f"Copied {format_size(written)} to {destination}")

        def failed(exc: BaseException) -> None:
            self._idle()
            self._token = None
            try:
                os.unlink(destination)
            except OSError:
                pass
            self._status(f"Copy failed: {exc}")

        self._busy(f"Copying {entry.name}…")
        self.background.submit(work, done, failed)

    def _copy_directory(self, scope_id: str, path: str, entry: Entry) -> None:
        parent = filedialog.askdirectory(
            title=f"Copy folder “{entry.name}” into…")
        if not parent:
            return
        destination = os.path.join(parent, entry.name)

        token = CancelToken()
        self._token = token
        session = self.session
        background = self.background

        def work() -> Tuple[int, int]:
            files = session.walk(scope_id, path)
            total = sum(size for _rel, size, _full in files)
            background.report(0, total)
            done = 0
            for rel, size, full in files:
                if token.cancelled:
                    raise Cancelled()
                target = os.path.join(destination, *rel.split("/"))
                os.makedirs(os.path.dirname(target) or destination,
                            exist_ok=True)
                read = session.file_reader(scope_id, full)
                offset = 0
                with open(target, "wb") as handle:
                    while offset < size:
                        if token.cancelled:
                            raise Cancelled()
                        chunk = read(offset, min(COPY_CHUNK, size - offset))
                        if not chunk:
                            break
                        handle.write(chunk)
                        offset += len(chunk)
                        done += len(chunk)
                        background.report(done, total)
            return done, len(files)

        def done(result: Tuple[int, int]) -> None:
            self._idle()
            self._token = None
            written, count = result
            self._status(f"Copied {count} file(s), {format_size(written)}, "
                         f"to {destination}")

        def failed(exc: BaseException) -> None:
            self._idle()
            self._token = None
            self._status(f"Copy failed after {destination}: {exc}")

        self._busy(f"Copying folder {entry.name}…")
        self.background.submit(work, done, failed)

    def cancel(self) -> None:
        if self._token is not None:
            self._token.cancel()
            self._status("Cancelling…")
