"""Session behaviour, without Tk."""

from __future__ import annotations

import pytest

from vhdpeek.session import Session

from tests.gui_support import SAMPLE


class TestSession:
    def test_open_lists_every_partition(self, gui_images):
        session = Session()
        try:
            session.open(gui_images["four"])
            assert len(session.volumes) == 4
            kinds = [v.fs_type for v in session.volumes]
            assert kinds == ["unknown", "fat32", "ext", "ext"]
            # Only the ones with a filesystem become scopes.
            assert [s.id for s in session.scopes] == ["p1", "p2", "p3"]
        finally:
            session.close()

    def test_nothing_is_opened_by_open(self, gui_images):
        """open() must not read any directory."""
        session = Session()
        try:
            session.open(gui_images["ext4"])
            assert session.scopes[0].id == "p0"
        finally:
            session.close()

    def test_read_through_scope(self, gui_images):
        session = Session()
        try:
            session.open(gui_images["ext4"])
            names = {e.name for e in session.list_dir("p0", "")}
            assert {"docs", "data", "readme.txt"} <= names
            assert session.read_file("p0", "/readme.txt") == SAMPLE["readme.txt"]
        finally:
            session.close()

    def test_unknown_scope_raises(self, gui_images):
        session = Session()
        try:
            session.open(gui_images["ext4"])
            with pytest.raises(KeyError):
                session.list_dir("nope", "")
        finally:
            session.close()

    def test_mount_iso_creates_a_new_scope(self, gui_images):
        session = Session()
        try:
            session.open(gui_images["iso_inside"])
            scope = session.mount_iso("p0", "/casper/tiny.iso")
            assert scope.kind == "iso"
            assert scope.parent_scope == "p0"
            assert scope.parent_path == "/casper/tiny.iso"
            assert scope.id in {s.id for s in session.scopes}

            # The partition is still browsable; mounting did not replace it.
            assert "casper" in {e.name for e in session.list_dir("p0", "")}
            assert "readme.txt" in {e.name for e in session.list_dir(scope.id, "")}
            assert session.read_file(scope.id, "/readme.txt") == SAMPLE["readme.txt"]
        finally:
            session.close()

    def test_mount_is_idempotent_per_path(self, gui_images):
        session = Session()
        try:
            session.open(gui_images["iso_inside"])
            first = session.mount_iso("p0", "/casper/tiny.iso")
            again = session.mounted_at("p0", "/casper/tiny.iso")
            assert again is not None and again.id == first.id
        finally:
            session.close()

    def test_two_isos_get_separate_scopes(self, gui_images):
        session = Session()
        try:
            session.open(gui_images["iso_inside"])
            a = session.mount_iso("p0", "/casper/tiny.iso")
            b = session.mount_iso("p0", "/casper/tiny.iso")
            assert a.id != b.id
        finally:
            session.close()

    def test_walk_lists_files_recursively(self, gui_images):
        session = Session()
        try:
            session.open(gui_images["ext4"])
            found = {rel: size for rel, size, _full in session.walk("p0", "")}
            assert found["readme.txt"] == len(SAMPLE["readme.txt"])
            assert found["docs/manual.txt"] == 15
            assert found["data/sub/note.txt"] == 12
        finally:
            session.close()
