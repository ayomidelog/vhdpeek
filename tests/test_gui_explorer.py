"""The explorer tree: partitions, lazy expansion, ISO nesting, preview."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter", reason="GUI tests need Tk")

from tests.fixtures import fsgen, vhdgen
from tests.gui_support import (SAMPLE, child, expand, listed, node,
                               open_and_wait, pump, wait_idle)
from vhdpeek.gui import make_iid


class TestExplorer:
    def test_shows_every_partition_and_nothing_else(self, app, gui_images):
        """The tree opens on the partitions; it does not jump into one."""
        open_and_wait(app, gui_images["four"])

        top = app.tree.get_children("")
        assert len(top) == 4
        assert [app.tree.item(i, "text") for i in top] == [
            "Partition 0", "Partition 1", "Partition 2", "Partition 3"]

        # Nothing is expanded, and no partition has been read yet.
        for iid in top:
            assert not app.tree.item(iid, "open")
        assert not listed(app, node(app, make_iid("p3", "")))

    def test_partition_without_filesystem_is_shown(self, app, gui_images):
        open_and_wait(app, gui_images["four"])
        values = app.tree.item(node(app, make_iid("p0", "")), "values")
        assert "no filesystem" in values[1]

    def test_single_partition_image_opens_that_partition(self, app, gui_images):
        open_and_wait(app, gui_images["ext4"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        names = {app.tree.item(i, "text")
                 for i in app.tree.get_children(root_iid)}
        assert {"docs", "data", "readme.txt"} <= names

    def test_expanding_a_partition_lists_its_root(self, app, gui_images):
        open_and_wait(app, gui_images["four"])
        root_iid = node(app, make_iid("p3", ""))
        assert not listed(app, root_iid)     # not read yet

        expand(app, root_iid)
        names = {app.tree.item(i, "text")
                 for i in app.tree.get_children(root_iid)}
        assert {"etc", "boot"} <= names

    def test_expanding_is_lazy(self, app, gui_images):
        open_and_wait(app, gui_images["four"])
        root_iid = node(app, make_iid("p3", ""))
        expand(app, root_iid)

        etc = child(app, root_iid, "etc")
        assert not listed(app, etc)          # still just a placeholder

        expand(app, etc)
        names = {app.tree.item(i, "text") for i in app.tree.get_children(etc)}
        assert names == {"os-release", "hostname"}

    def test_preview_shows_file_text(self, app, gui_images):
        open_and_wait(app, gui_images["four"])
        root_iid = node(app, make_iid("p3", ""))
        expand(app, root_iid)
        etc = child(app, root_iid, "etc")
        expand(app, etc)

        osrel = child(app, etc, "os-release")
        app.tree.selection_set(osrel)
        app.tree.focus(osrel)
        app._node_selected(None)
        wait_idle(app)
        pump(app, lambda: "PRETTY_NAME" in app.preview.get("1.0", "end"))
        assert "Ubuntu 24.04.1 LTS" in app.preview.get("1.0", "end")

    def test_preview_of_binary_is_hex(self, app, gui_images):
        open_and_wait(app, gui_images["ext4"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        data = child(app, root_iid, "data")
        expand(app, data)

        blob = child(app, data, "blob.bin")
        app.tree.selection_set(blob)
        app.tree.focus(blob)
        app._node_selected(None)
        wait_idle(app)
        pump(app, lambda: "00000000" in app.preview.get("1.0", "end"))
        assert "00 01 02 03 04 05" in app.preview.get("1.0", "end")

    def test_iso_mounts_inline_under_its_file(self, app, gui_images):
        """An ISO is a child of the file it lives in, not a separate window."""
        open_and_wait(app, gui_images["iso_inside"])
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))

        casper = child(app, root_iid, "casper")
        expand(app, casper)

        iso_node = child(app, casper, "tiny.iso")
        assert not listed(app, iso_node)      # not mounted until expanded
        expand(app, iso_node)

        # The ISO's contents appear directly under the file that holds it.
        names = {app.tree.item(i, "text")
                 for i in app.tree.get_children(iso_node)}
        assert {"docs", "data", "readme.txt"} <= names
        assert "ISO" in app.status_label.cget("text")

        # The partition is untouched: casper is still there.
        assert app.tree.exists(casper)

    def test_non_iso_with_iso_extension_fails_cleanly(self, app, tmp_path, gui_images):
        # Reuse the ext4 image but rename a file to look like an ISO.
        with_iso = dict(SAMPLE)
        with_iso["casper/"] = b""
        with_iso["casper/fake.iso"] = b"this is not an iso9660 image at all"
        path = tmp_path / "fake.vhd"
        path.write_bytes(vhdgen.wrap_fixed_vhd(
            vhdgen.assemble_disk(fsgen.build_ext4(with_iso), "mbr", 1)))

        open_and_wait(app, str(path))
        root_iid = node(app, make_iid("p0", ""))
        pump(app, lambda: listed(app, root_iid))
        casper = child(app, root_iid, "casper")
        expand(app, casper)
        iso_node = child(app, casper, "fake.iso")
        expand(app, iso_node)
        assert "not an ISO" in app.status_label.cget("text")
        assert app.tree.exists(casper)

    def test_vhdx_opens(self, app, gui_images):
        open_and_wait(app, gui_images["vhdx"])
        assert "VHDX" in app.info_label.cget("text")
        assert app.tree.get_children("")

    def test_missing_file_reports_an_error(self, app, tmp_path):
        app.open_path(str(tmp_path / "nope.vhd"))
        wait_idle(app)
        assert "Ready" not in app.status_label.cget("text")
        assert app.status_label.cget("text") != ""
