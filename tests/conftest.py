"""Fixtures shared by every test module."""

from __future__ import annotations

import pytest

try:                                  # a minimal Python may lack Tk
    import tkinter as tk
except ImportError:                   # pragma: no cover - platform dependent
    tk = None

from tests.fixtures import fsgen, vhdgen
from tests.gui_support import SAMPLE, UBUNTU_LIKE

if tk is not None:
    from vhdpeek.gui import App
else:                                 # pragma: no cover
    App = None

__all__ = ["gui_images", "tk_root", "app"]


@pytest.fixture(scope="module")
def gui_images(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("gui-images")
    iso = fsgen.build_iso(SAMPLE)

    with_iso = dict(SAMPLE)
    with_iso["casper/"] = b""
    with_iso["casper/tiny.iso"] = iso

    paths = {
        "fat32": out / "fat32.vhd",
        "ext4": out / "ext4.vhd",
        "iso_inside": out / "iso_inside.vhd",
        "vhdx": out / "disk.vhdx",
        "four": out / "four.vhd",
    }
    paths["fat32"].write_bytes(vhdgen.wrap_fixed_vhd(
        vhdgen.assemble_disk(fsgen.build_fat32(SAMPLE), "mbr", 1)))
    paths["ext4"].write_bytes(vhdgen.wrap_fixed_vhd(
        vhdgen.assemble_disk(fsgen.build_ext4(SAMPLE), "mbr", 1)))
    paths["iso_inside"].write_bytes(vhdgen.wrap_fixed_vhd(
        vhdgen.assemble_disk(fsgen.build_ext4(with_iso), "mbr", 1)))
    paths["vhdx"].write_bytes(vhdgen.wrap_vhdx(
        vhdgen.assemble_disk(fsgen.build_fat32(SAMPLE), "mbr", 1)))

    # A four-partition GPT disk, the shape of a real Ubuntu cloud image:
    # BIOS boot (no filesystem), EFI (FAT32), /boot (ext4), root (ext4).
    efi = fsgen.build_fat32({"EFI/": b"", "EFI/BOOT/": b"",
                             "EFI/BOOT/BOOTX64.EFI": b"MZ" + b"\x00" * 64})
    boot = fsgen.build_ext4({"grub.cfg": b"set timeout=0\n"})
    root = fsgen.build_ext4(UBUNTU_LIKE)
    paths["four"].write_bytes(vhdgen.wrap_fixed_vhd(vhdgen.assemble_disk_multi([
        (2048, b"\x00" * (4 << 20), 0x83,
         "21686148-6449-6E6F-744E-656564454649", "BIOS boot"),
        (10240, efi, 0xEF,
         "C12A7328-F81F-11D2-BA4B-00A0C93EC93B", "EFI System"),
        (227328, boot, 0x83,
         "BC13C2FF-59E6-4262-A352-B275FD6F7172", "Linux extended boot"),
        (409600, root, 0x83,
         "0FC63DAF-8483-4772-8E79-3D69D8477DE4", "Linux filesystem"),
    ])))

    return {name: str(path) for name, path in paths.items()}


@pytest.fixture(scope="session")
def tk_root():
    """
    One Tk interpreter for the whole session.

    Creating and destroying a fresh `Tk()` per test intermittently fails to
    initialise Tcl on Windows ("can't find a usable init.tcl"), so each test
    gets a Toplevel on a shared root instead.
    """
    if tk is None:
        pytest.skip("tkinter is not installed")
    try:
        root = tk.Tk()
    except tk.TclError as exc:            # no display
        pytest.skip(f"no display: {exc}")
    root.withdraw()                        # keep the tests off-screen
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root):
    window = tk.Toplevel(tk_root)
    window.withdraw()
    instance = App(window)
    try:
        yield instance
    finally:
        instance.background.shutdown()
        instance.session.close()
        window.destroy()


