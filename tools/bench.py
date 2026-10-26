"""
Benchmark vhdpeek: local throughput, HTTP request counts, and parse cost.

Latency on a real network is dominated by request count, not bytes, so the
numbers that matter are requests-per-operation and bytes-per-operation.
"""

from __future__ import annotations

import http.server
import os
import statistics
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vhdpeek.core.containers import detect_and_parse
from vhdpeek.core.partitions import PartitionView, parse_partitions
from vhdpeek.core.source import HTTPSource, LocalSource
from vhdpeek.core.volume import BytesView, ReaderView
from vhdpeek.fs.ext4 import Ext4Reader
from vhdpeek.fs.fat import FatReader
from vhdpeek.fs.iso import IsoReader
from vhdpeek.fs.ntfs import NtfsReader

from tests.fixtures import fsgen, vhdgen


def timeit(fn, repeat=5):
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


class CountingView(BytesView):
    def __init__(self, data, sector_size=512):
        super().__init__(data, sector_size)
        self.calls = 0
        self.bytes = 0

    def read(self, offset, size):
        self.calls += 1
        self.bytes += size
        return super().read(offset, size)


def bench_reader(label, reader, root_paths):
    print(f"\n{label}")
    for path in root_paths:
        entry = reader.stat(path) if hasattr(reader, "stat") else None
        size = entry.size if entry else None
        try:
            t = timeit(lambda: reader.list_dir(path), repeat=3)
            print(f"  list_dir({path!r:22}) {t*1e3:7.2f} ms")
        except Exception as exc:
            print(f"  list_dir({path!r:22}) failed: {exc}")
        if size:
            t = timeit(lambda: reader.read_file(path), repeat=3)
            mb = size / (1 << 20)
            print(f"  read_file({path!r:22}) {t*1e3:7.2f} ms  "
                  f"{mb/(t or 1e-9):8.1f} MiB/s  ({size:,} B)")


def main() -> None:
    sample = {
        "readme.txt": b"Hello from vhdpeek test\nLine 2\n",
        "docs/": b"", "docs/manual.txt": b"Manual content\n",
        "data/": b"", "data/blob.bin": b"\x00\x01\x02\x03\x04\x05" * 100,
        "data/sub/": b"", "data/sub/note.txt": b"nested note\n",
    }
    big = {"big.bin": bytes(range(256)) * 16384}  # 4 MiB

    print("=" * 68)
    print("Parse cost: open image + read partition table + mount filesystem")
    print("=" * 68)

    cases = {}
    for name, data in (
        ("fat32", fsgen.build_fat32(sample)),
        ("fat16", fsgen.build_fat16(sample)),
        ("fat12", fsgen.build_fat12(sample)),
        ("ntfs", fsgen.build_ntfs(sample)),
        ("ext4", fsgen.build_ext4(sample)),
        ("iso", fsgen.build_iso(sample)),
    ):
        cases[name] = data

    disk = vhdgen.assemble_disk(cases["fat32"], "mbr", 1)
    containers = {
        "fixed": vhdgen.wrap_fixed_vhd(disk),
        "dynamic": vhdgen.wrap_dynamic_vhd(disk),
        "vhdx": vhdgen.wrap_vhdx(disk),
    }
    Path("bench_data").mkdir(exist_ok=True)
    for name, blob in containers.items():
        ext = ".vhdx" if name == "vhdx" else ".vhd"
        Path(f"bench_data/{name}{ext}").write_bytes(blob)

    for name, blob in cases.items():
        # Wrap the bare filesystem in a fixed VHD so the full stack runs.
        path = f"bench_data/{name}.vhd"
        Path(path).write_bytes(
            vhdgen.wrap_fixed_vhd(vhdgen.assemble_disk(blob, "mbr", 1)))

        def open_all(p=path):
            src = LocalSource(p)
            d = detect_and_parse(src)
            parts = parse_partitions(d)
            if parts:
                reader = {  # noqa: E741
                    "fat32": FatReader, "fat16": FatReader, "fat12": FatReader,
                    "ntfs": NtfsReader, "ext4": Ext4Reader, "iso": IsoReader,
                }[name](PartitionView(d, parts[0]))
                reader.list_dir("")
            src.close()

        t = timeit(open_all)
        print(f"  {name:6} open+list root: {t*1e3:7.2f} ms")

    for name, blob in containers.items():
        path = f"bench_data/{name}" + (".vhdx" if name == "vhdx" else ".vhd")

        def open_vhd(p=path):
            src = LocalSource(p)
            d = detect_and_parse(src)
            parts = parse_partitions(d)
            if parts:
                FatReader(PartitionView(d, parts[0])).list_dir("")
            src.close()

        t = timeit(open_vhd)
        print(f"  {name:6} open+list root: {t*1e3:7.2f} ms")

    print("\n" + "=" * 68)
    print("Reads per operation (what a network actually pays for)")
    print("=" * 68)

    for name, data in cases.items():
        view = CountingView(data, sector_size=2048 if name == "iso" else 512)
        cls = {"fat32": FatReader, "fat16": FatReader, "fat12": FatReader,
               "ntfs": NtfsReader, "ext4": Ext4Reader, "iso": IsoReader}[name]
        reader = cls(view)
        view.calls = view.bytes = 0
        reader.list_dir("")
        list_calls, list_bytes = view.calls, view.bytes
        view.calls = view.bytes = 0
        if hasattr(reader, "stat") and reader.stat("/readme.txt"):
            reader.read_file("/readme.txt")
        read_calls, read_bytes = view.calls, view.bytes
        print(f"  {name:6} list root: {list_calls:3d} reads, "
              f"{list_bytes:7,} B   read 30 B file: {read_calls:2d} reads, "
              f"{read_bytes:6,} B")

    print("\n" + "=" * 68)
    print("Large file throughput, local")
    print("=" * 68)

    for name, builder in (("fat32", fsgen.build_fat32), ("ntfs", fsgen.build_ntfs),
                          ("ext4", fsgen.build_ext4), ("iso", fsgen.build_iso)):
        data = builder(big)
        view = BytesView(data, sector_size=2048 if name == "iso" else 512)
        cls = {"fat32": FatReader, "ntfs": NtfsReader, "ext4": Ext4Reader,
               "iso": IsoReader}[name]
        reader = cls(view)
        size = 4 << 20
        t = timeit(lambda: reader.read_file("/big.bin"), repeat=3)
        print(f"  {name:6} 4 MiB read: {t*1e3:7.2f} ms  "
              f"{(size/(1 << 20))/(t or 1e-9):8.1f} MiB/s")

    print("\n" + "=" * 68)
    print("HTTP: requests and bytes per operation (localhost)")
    print("=" * 68)

    root = str(Path("bench_data").resolve())
    stats = {"gets": 0, "bytes": 0, "latency": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_GET(self):
            path = os.path.join(root, os.path.basename(self.path))
            size = os.path.getsize(path)
            header = self.headers.get("Range")
            start_t = time.perf_counter()
            if header and header.startswith("bytes="):
                first, last = header[6:].split("-")
                first, last = int(first), min(int(last), size - 1)
                with open(path, "rb") as fh:
                    fh.seek(first)
                    data = fh.read(last - first + 1)
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {first}-{last}/{size}")
            else:
                with open(path, "rb") as fh:
                    data = fh.read()
                self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            stats["gets"] += 1
            stats["bytes"] += len(data)
            stats["latency"].append(time.perf_counter() - start_t)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    # The first HTTPSource in a process pays for importing/initialising the
    # HTTP stack (~250 ms here). Warm it so the timings measure the library.
    warm = HTTPSource(f"{base}/fixed.vhd")
    warm.read(0, 8)
    warm.close()

    for name in ("fixed.vhd", "dynamic.vhd", "vhdx.vhdx"):
        def open_list(n=name):
            stats.update(gets=0, bytes=0, latency=[])
            source = HTTPSource(f"{base}/{n}")
            disk = detect_and_parse(source)
            parts = parse_partitions(disk)
            FatReader(PartitionView(disk, parts[0])).list_dir("")
            source.close()

        elapsed = timeit(open_list, repeat=3)
        med = statistics.median(stats["latency"]) * 1e3 if stats["latency"] else 0
        print(f"  {name:12} open+list root: {elapsed*1e3:7.2f} ms, "
              f"{stats['gets']:2d} GETs, {stats['bytes']:8,} B, "
              f"median request {med:.2f} ms")

    # 60 GiB sparse image with a nested ISO, the real-world case.
    from tools import make_ubuntu_image as ubuntu_gen
    ubuntu_disk = ubuntu_gen.build_ubuntu_disk()
    Path("bench_data/ubuntu.vhd").write_bytes(
        ubuntu_gen.to_sparse_vhd(ubuntu_disk))
    stored = os.path.getsize("bench_data/ubuntu.vhd")

    def open_ubuntu():
        stats.update(gets=0, bytes=0, latency=[])
        src = HTTPSource(f"{base}/ubuntu.vhd")
        disk = detect_and_parse(src)
        reader = Ext4Reader(PartitionView(disk, parse_partitions(disk)[0]))
        reader.list_dir("")
        src.close()

    elapsed = timeit(open_ubuntu, repeat=3)
    print(f"\n  {'ubuntu.vhd':12} 60 GiB: open+list root: {elapsed*1e3:7.2f} ms, "
          f"{stats['gets']:2d} GETs, {stats['bytes']:8,} B")

    source = HTTPSource(f"{base}/ubuntu.vhd")
    d = detect_and_parse(source)
    ext = Ext4Reader(PartitionView(d, parse_partitions(d)[0]))
    ext.list_dir("")

    stats.update(gets=0, bytes=0, latency=[])
    start = time.perf_counter()
    entry = ext.stat("/casper/ubuntu-24.04-desktop-amd64.iso")
    iso = IsoReader(ReaderView(ext.file_reader(entry.path), entry.size))
    iso.list_dir("")
    elapsed = time.perf_counter() - start
    print(f"  {'':12} enter nested ISO:        {elapsed*1e3:7.2f} ms, "
          f"{stats['gets']:2d} GETs, {stats['bytes']:8,} B")

    stats.update(gets=0, bytes=0, latency=[])
    t0 = time.perf_counter()
    data = iso.read_file("/casper/filesystem.squashfs")
    elapsed = time.perf_counter() - t0
    print(f"  {'':12} read 2 MiB from ISO:     {elapsed*1e3:7.2f} ms, "
          f"{stats['gets']:2d} GETs, {stats['bytes']:8,} B, "
          f"{(len(data)/(1 << 20))/(elapsed or 1e-9):8.1f} MiB/s")
    source.close()
    server.shutdown()
    server.server_close()
    print(f"\n  (image on disk: {stored:,} B; a full download would be that much)")


if __name__ == "__main__":
    main()
