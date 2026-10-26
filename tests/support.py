"""Shared constants, fixtures and helpers for the vhdpeek test suite.

The fixture builders live in ``tests.fixtures`` and are cross-checked against
independent readers in ``test_generators.py``.
"""

from __future__ import annotations

import http.server
import os
import threading
import time

import pytest

from vhdpeek.core.containers import detect_and_parse
from vhdpeek.core.source import LocalSource

from tests.fixtures import fsgen, vhdgen

SAMPLE = {
    "readme.txt": b"Hello from vhdpeek test\nLine 2\n",
    "docs/": b"",
    "docs/manual.txt": b"Manual content\n",
    "data/": b"",
    "data/blob.bin": b"\x00\x01\x02\x03\x04\x05" * 100,
    "data/sub/": b"",
    "data/sub/note.txt": b"nested note\n",
    "docs/long name with spaces.md": b"long filename body\n",
}

EXPECTED = {
    "/readme.txt": b"Hello from vhdpeek test\nLine 2\n",
    "/docs/manual.txt": b"Manual content\n",
    "/data/blob.bin": b"\x00\x01\x02\x03\x04\x05" * 100,
    "/data/sub/note.txt": b"nested note\n",
    "/docs/long name with spaces.md": b"long filename body\n",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def images(tmp_path_factory) -> dict:
    """Container images and raw filesystem images, generated once."""
    out = tmp_path_factory.mktemp("images")

    fat32 = fsgen.build_fat32(SAMPLE)
    fat16 = fsgen.build_fat16(SAMPLE)
    fat12 = fsgen.build_fat12(SAMPLE)
    ntfs = fsgen.build_ntfs(SAMPLE)
    ext4 = fsgen.build_ext4(SAMPLE)
    iso = fsgen.build_iso(SAMPLE)

    disk = vhdgen.assemble_disk(fat32, "mbr", start_lba=1)
    gpt_disk = vhdgen.assemble_disk(ext4, "gpt", start_lba=2048,
                                    total_sectors=8192)

    paths = {
        "fixed": out / "test_fixed.vhd",
        "dynamic": out / "test_dynamic.vhd",
        "vhdx": out / "test_vhdx.vhdx",
        "gpt_ext4": out / "test_gpt_ext4.vhd",
    }
    paths["fixed"].write_bytes(vhdgen.wrap_fixed_vhd(disk))
    paths["dynamic"].write_bytes(vhdgen.wrap_dynamic_vhd(disk))
    paths["vhdx"].write_bytes(vhdgen.wrap_vhdx(disk))
    paths["gpt_ext4"].write_bytes(vhdgen.wrap_fixed_vhd(gpt_disk))

    return {
        "dir": str(out),
        "containers": {name: str(path) for name, path in paths.items()},
        "raw": {
            "fat32": fat32, "fat16": fat16, "fat12": fat12,
            "ntfs": ntfs, "ext4": ext4, "iso": iso,
        },
        "disk": disk,
    }

@pytest.fixture(scope="session")
def http_server(images):
    """Range-capable HTTP server serving the generated images."""
    directory = images["dir"]

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_HEAD(self):
            path = os.path.join(directory, os.path.basename(self.path))
            if not os.path.isfile(path):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        def do_GET(self):
            path = os.path.join(directory, os.path.basename(self.path))
            if not os.path.isfile(path):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            size = os.path.getsize(path)
            header = self.headers.get("Range")
            if header and header.startswith("bytes="):
                first, last = header[6:].split("-")
                first, last = int(first), int(last)
                last = min(last, size - 1)
                with open(path, "rb") as handle:
                    handle.seek(first)
                    data = handle.read(last - first + 1)
                self.send_response(206)
                self.send_header("Content-Range",
                                 f"bytes {first}-{last}/{size}")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(data)
            else:
                with open(path, "rb") as handle:
                    data = handle.read()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()

def open_disk(path: str):
    return detect_and_parse(LocalSource(path))
