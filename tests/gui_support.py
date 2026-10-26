"""
Shared constants and helpers for the GUI tests.

The fixtures live in `conftest.py`, so every test module sees them without
importing them.
"""

from __future__ import annotations

import time

from vhdpeek.gui.treeids import PLACEHOLDER

from tests.support import SAMPLE

UBUNTU_LIKE = {
    "etc/": b"",
    "etc/os-release": b'PRETTY_NAME="Ubuntu 24.04.1 LTS"\n',
    "etc/hostname": b"ayovps\n",
    "boot/": b"",
    "boot/grub/": b"",
    "boot/grub/grub.cfg": b"set timeout=5\n",
}

__all__ = [
    "SAMPLE",
    "UBUNTU_LIKE",
    "pump",
    "wait_idle",
    "node",
    "child",
    "listed",
    "open_and_wait",
    "expand",
]


def pump(app, predicate, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.root.update()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the GUI")


def wait_idle(app, timeout: float = 30.0) -> None:
    pump(app, lambda: not app.background.busy, timeout)


def node(app, iid: str) -> str:
    assert app.tree.exists(iid), f"missing tree node {iid!r}"
    return iid


def child(app, parent: str, name: str) -> str:
    for iid in app.tree.get_children(parent):
        if app.tree.item(iid, "text") == name:
            return iid
    raise AssertionError(f"no child {name!r} under {parent!r}")


def listed(app, iid: str) -> bool:
    """True once `iid` has been loaded: no placeholder child remains."""
    return not any(PLACEHOLDER in c for c in app.tree.get_children(iid))


def open_and_wait(app, path: str) -> None:
    app.open_path(path)
    wait_idle(app)
    pump(app, lambda: app.tree.get_children())


def expand(app, iid: str) -> None:
    app.tree.focus(iid)
    app.tree.item(iid, open=True)
    app._node_opened(None)
    wait_idle(app)
    pump(app, lambda: listed(app, iid))
