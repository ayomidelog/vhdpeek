"""
Tree behaviour: populate, expand, mount nested ISOs, preview.

The tree is a real explorer: the image's partitions are the top level, and
nothing is opened until you expand it. An ISO stored inside a filesystem
appears under the file it lives in when you expand that file, so the
structure on disk is never hidden.
"""

from __future__ import annotations

import os
from typing import List

from ..core.volume import Entry, format_size
from ..fs import looks_like_iso
from ..session import Scope
from .preview import PREVIEW_LIMIT, render
from .treeids import PLACEHOLDER, make_iid, split_iid


class TreeMixin:
    """Mixed into `App`; expects `self.tree`, `self.session`, `self.background`."""

    def _populate(self) -> None:
        """Show the partitions. Nothing is expanded or opened."""
        self.tree.delete(*self.tree.get_children())
        self._selected = None
        self._set_preview("")
        self.location.configure(text="")

        for volume in self.session.volumes:
            iid = make_iid(f"p{volume.index}", "")
            if volume.fs_type == "unknown":
                self.tree.insert(
                    "", "end", iid=iid, text=volume.title,
                    values=(format_size(volume.size_bytes),
                            f"no filesystem ({volume.type})"),
                )
                continue
            self.tree.insert(
                "", "end", iid=iid, text=volume.title,
                values=(format_size(volume.size_bytes),
                        f"{volume.fs_type}  {volume.label}".strip()),
            )
            self.tree.insert(iid, "end", iid=f"{iid}{PLACEHOLDER}",
                             text="loading…")

        self._expand_partitions_with_content()

    def _expand_partitions_with_content(self) -> None:
        """Open single-partition images; leave multi-partition ones closed."""
        if len(self.session.scopes) != 1:
            return
        scope = self.session.scopes[0]
        iid = make_iid(scope.id, "")
        if self.tree.exists(iid):
            self.tree.item(iid, open=True)
            self._load(iid)

    def _load(self, iid: str) -> None:
        """List a node's directory, or mount an ISO stored in it."""
        scope_id, path = split_iid(iid)
        session = self.session

        if path and looks_like_iso(path):
            mounted = session.mounted_at(scope_id, path)
            if mounted is not None:
                self._fill(iid, mounted.id, "")
                return
            self._busy(f"Mounting {os.path.basename(path)}…")

            def work() -> Scope:
                return session.mount_iso(scope_id, path)

            def done(scope: Scope) -> None:
                self._idle()
                # The ISO's contents become children of the file that holds
                # it, so the on-disk structure stays visible.
                self._fill(iid, scope.id, "")
                self.tree.item(iid, open=True)
                self._status(f"Mounted {scope.label}"
                             + (f"  ·  {scope.detail}" if scope.detail else ""))

            def failed(exc: BaseException) -> None:
                self._idle()
                self._clear_placeholder(iid)
                self._status(f"{os.path.basename(path)} is not an ISO 9660 "
                             f"image: {exc}")

            self.background.submit(work, done, failed)
            return

        self._busy(f"Listing {path or '/'}…")

        def work() -> List[Entry]:
            return session.list_dir(scope_id, path)

        def done(entries: List[Entry]) -> None:
            self._idle()
            self._fill(iid, scope_id, path)
            self._status(f"{len(entries)} entries in {path or '/'}")

        def failed(exc: BaseException) -> None:
            self._idle()
            self._clear_placeholder(iid)
            self._status(f"Cannot list {path or '/'}: {exc}")

        self.background.submit(work, done, failed)

    def _clear_placeholder(self, iid: str) -> None:
        for child in self.tree.get_children(iid):
            if PLACEHOLDER in child:
                self.tree.delete(child)

    def _fill(self, parent: str, scope_id: str, path: str) -> None:
        self._clear_placeholder(parent)
        for child in self.tree.get_children(parent):
            self.tree.delete(child)

        try:
            entries = self.session.list_dir(scope_id, path)
        except Exception as exc:
            self._status(f"Cannot list {path or '/'}: {exc}")
            return

        for entry in sorted(entries, key=lambda e: (not e.is_dir,
                                                    e.name.lower())):
            child_path = f"{path}/{entry.name}" if path else entry.path
            iid = make_iid(scope_id, child_path)
            kind = "folder" if entry.is_dir else (
                "ISO image" if looks_like_iso(entry.name) else "file")
            self.tree.insert(
                parent, "end", iid=iid, text=entry.name,
                values=("" if entry.is_dir else format_size(entry.size), kind),
            )
            if entry.is_dir or looks_like_iso(entry.name):
                self.tree.insert(iid, "end", iid=f"{iid}{PLACEHOLDER}",
                                 text="loading…")

    def _node_opened(self, _event: object) -> None:
        node = self.tree.focus()
        if not node or PLACEHOLDER in node:
            return
        children = self.tree.get_children(node)
        if len(children) == 1 and PLACEHOLDER in children[0]:
            self._load(node)

    def _node_selected(self, _event: object) -> None:
        node = self.tree.focus()
        if not node or PLACEHOLDER in node:
            return
        self._selected = node

        scope_id, path = split_iid(node)
        values = self.tree.item(node, "values")
        kind = values[1] if len(values) > 1 else ""
        self.location.configure(text=self._describe(scope_id, path))

        if kind == "folder" or kind.startswith("no filesystem"):
            self._set_preview("")
            return
        if path and looks_like_iso(path):
            self._set_preview("")
            return
        if not path:
            self._set_preview("")
            return
        self._preview_file(scope_id, path)

    def _describe(self, scope_id: str, path: str) -> str:
        try:
            scope = self.session.scope(scope_id)
        except KeyError:
            return ""
        where = f"{scope.label} ({scope.fs_type})"
        if scope.kind == "iso":
            where = f"{scope.label} — ISO inside {scope.parent_path}"
        return f"{where}  ·  {path or '/'}"

    def _node_activated(self, event: object) -> None:
        node = self.tree.focus()
        if not node or PLACEHOLDER in node:
            return
        if self.tree.identify_region(event.x, event.y) != "tree":
            return
        if self.tree.get_children(node):
            self.tree.item(node, open=not self.tree.item(node, "open"))

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _set_preview(self, text: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def _preview_file(self, scope_id: str, path: str) -> None:
        try:
            entry = self.session.stat(scope_id, path)
        except Exception:
            return
        if entry is None or entry.is_dir:
            self._set_preview("")
            return

        self._busy(f"Reading {entry.name}…")
        session = self.session
        want = min(entry.size, PREVIEW_LIMIT)

        def work() -> bytes:
            return session.read_file(scope_id, path, 0, want)

        def done(data: bytes) -> None:
            self._idle()
            self._set_preview(render(data))
            note = "" if entry.size <= PREVIEW_LIMIT else \
                f"  (first {format_size(PREVIEW_LIMIT)} of " \
                f"{format_size(entry.size)})"
            self._status(f"{entry.name}  ·  {format_size(entry.size)}{note}")

        def failed(exc: BaseException) -> None:
            self._idle()
            self._set_preview(f"<cannot read: {exc}>")

        self.background.submit(work, done, failed)
