"""HTTP source tests: range requests, block cache and size discovery."""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from vhdpeek.core.containers import detect_and_parse
from vhdpeek.core.partitions import PartitionView, parse_partitions
from vhdpeek.core.source import HTTPSource, make_source
from vhdpeek.fs.fat import FatReader

from tests.support import EXPECTED, http_server, images  # noqa: F401

__all__ = ["images", "http_server"]

class TestHttp:
    @pytest.mark.parametrize("name", ["test_fixed.vhd", "test_dynamic.vhd",
                                      "test_vhdx.vhdx"])
    def test_container_over_range_requests(self, http_server, images, name):
        source = make_source(f"{http_server}/{name}")
        assert isinstance(source, HTTPSource)
        disk = detect_and_parse(source)
        expected = images["disk"]
        assert disk.read(0, len(expected)) == expected

    def test_filesystem_over_http(self, http_server):
        source = make_source(f"{http_server}/test_fixed.vhd")
        disk = detect_and_parse(source)
        part = parse_partitions(disk)[0]
        reader = FatReader(PartitionView(disk, part))
        for path, expected in EXPECTED.items():
            assert reader.read_file(path) == expected, path

    def test_block_cache_does_not_mix_offsets(self, http_server):
        """Two small reads in one block must not return the first one twice."""
        source = make_source(f"{http_server}/test_vhdx.vhdx")
        second = source.read(1000, 100)
        first = source.read(0, 100)
        assert first != second
        assert source.read(0, 100) == source.read(0, 100)

    def test_non_range_server_is_refused_not_downloaded(self, tmp_path):
        """A server that ignores Range must fail loudly, not stream 60 GB."""
        from vhdpeek.core.source import RangeNotSupported

        payload = b"\xAA" * (12 << 20)
        path = tmp_path / "big.bin"
        path.write_bytes(payload)

        class NoRange(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def do_GET(self):
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), NoRange)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            source = HTTPSource(
                f"http://127.0.0.1:{server.server_address[1]}/big.bin")
            assert source.size == len(payload)
            assert source.read(1024, 64) == payload[1024:1088]
            with pytest.raises(RangeNotSupported):
                source.read(9 << 20, 512)
        finally:
            server.shutdown()
            server.server_close()

    def test_read_spanning_cache_blocks(self, http_server, images):
        """A read smaller than a block may still cross a block boundary."""
        payload = bytes(range(256)) * 64          # 16 KiB, easy to verify
        path = Path(images["dir"]) / "pattern.bin"
        path.write_bytes(payload)
        try:
            source = HTTPSource(f"{http_server}/pattern.bin", block_size=4096)
            assert source.size == len(payload)
            # Warm one block, then read across the boundary between blocks.
            assert source.read(0, 16) == payload[:16]
            for offset, size in ((4000, 200), (4090, 20), (8190, 4),
                                 (4096, 4096)):
                assert source.read(offset, size) == payload[offset:offset + size], \
                    (offset, size)
            # And with a cold cache, reading backwards.
            cold = HTTPSource(f"{http_server}/pattern.bin", block_size=4096)
            for offset in (8190, 4090, 4000, 0):
                assert cold.read(offset, 300) == payload[offset:offset + 300], \
                    offset
        finally:
            path.unlink(missing_ok=True)

    def test_size_discovery(self, http_server, images):
        source = make_source(f"{http_server}/test_fixed.vhd")
        assert source.size == Path(images["containers"]["fixed"]).stat().st_size
