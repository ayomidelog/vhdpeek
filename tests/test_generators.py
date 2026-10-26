"""Generators must be valid according to independent readers.

A broken fixture invalidates the whole suite, so every builder is cross-checked
against a third-party reader that shares no code with it.
"""

from __future__ import annotations

import pytest

from tests.support import EXPECTED, images  # noqa: F401  (pytest fixture)

__all__ = ["images"]

class TestGenerators:
    """Guard the fixtures themselves; a broken fixture invalidates the suite."""

    def test_fat_images_read_by_pyfatfs(self, images, tmp_path):
        pyfatfs = pytest.importorskip("pyfatfs.PyFatFS")
        for kind in ("fat32", "fat16", "fat12"):
            path = tmp_path / f"{kind}.img"
            path.write_bytes(images["raw"][kind])
            fs = pyfatfs.PyFatFS(str(path), read_only=True)
            try:
                assert fs.readbytes("/README.TXT") == EXPECTED["/readme.txt"]
                assert fs.readbytes("/DATA/SUB/NOTE.TXT") == EXPECTED[
                    "/data/sub/note.txt"]
            finally:
                fs.close()

    def test_ext4_read_by_dissect(self, images, tmp_path):
        dissect = pytest.importorskip("dissect.extfs")
        path = tmp_path / "ext4.img"
        path.write_bytes(images["raw"]["ext4"])
        fs = dissect.ExtFS(open(path, "rb"))
        root = fs.root.listdir()
        assert root["readme.txt"].open().read() == EXPECTED["/readme.txt"]
        assert root["data"].listdir()["sub"].listdir()["note.txt"].open().read() \
            == EXPECTED["/data/sub/note.txt"]
        blob = root["data"].listdir()["blob.bin"].open().read()
        assert blob == EXPECTED["/data/blob.bin"]

    def test_ntfs_read_by_dissect(self, images, tmp_path):
        dissect = pytest.importorskip("dissect.ntfs")
        path = tmp_path / "ntfs.img"
        path.write_bytes(images["raw"]["ntfs"])
        fs = dissect.NTFS(open(path, "rb"))
        root = fs.mft.root.listdir()
        assert root["readme.txt"].dereference().open().read() == \
            EXPECTED["/readme.txt"]
        nested = root["data"].dereference().listdir()["sub"]
        assert nested.dereference().listdir()["note.txt"].dereference() \
            .open().read() == EXPECTED["/data/sub/note.txt"]

    def test_iso_read_by_pycdlib(self, images, tmp_path):
        pycdlib = pytest.importorskip("pycdlib")
        import io
        path = tmp_path / "test.iso"
        path.write_bytes(images["raw"]["iso"])
        iso = pycdlib.PyCdlib()
        iso.open(str(path))
        try:
            assert iso.has_rock_ridge()
            out = io.BytesIO()
            iso.get_file_from_iso_fp(out, rr_path="/data/sub/note.txt")
            assert out.getvalue() == EXPECTED["/data/sub/note.txt"]
        finally:
            iso.close()
