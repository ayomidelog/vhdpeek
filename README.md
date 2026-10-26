<p align="center">
  <img src="assets/vhdpeek.png" alt="VHDPeek" width="600">
</p>

<p align="center">
  <a href="../../actions/workflows/tests.yml"><img src="../../actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="license"></a>
</p>

Browse a VHD/VHDX disk image over HTTP or from a local file — no download, no
mount. Walks partitions and filesystems, and enters an ISO that lives *inside*
the image without extracting it.

## Install

**Windows** — take `vhdpeek-<version>-windows-x64.exe` from the
[releases page](../../releases) and run it. No Python, no installer, nothing
written outside the file. The `.zip` is the same binary, archived.

**Linux and macOS** — one line:

```bash
curl -fsSL https://raw.githubusercontent.com/ayomidelog/vhdpeek/main/install.sh | sh
```

Installs into `~/.local/share/vhdpeek` and links `vhdpeek` into `~/.local/bin`.
Undo with the same script and `--uninstall`.

**Anywhere** — `pip install .` from a checkout, or `python -m vhdpeek` with
nothing installed. Python 3.9+; `requests` only for `http(s)` sources.

## CLI

```bash
vhdpeek disk.vhd --parts        # partitions
vhdpeek disk.vhd                # tree (default)
vhdpeek disk.vhd --ls /var/log  # one directory
vhdpeek disk.vhd --cat /etc/os-release

vhdpeek https://example.com/disk.vhdx --max-depth 2

vhdpeek ubuntu.vhd --iso /casper/ubuntu-24.04-desktop-amd64.iso --ls /
```

`--part N` picks a partition, `--fs` overrides detection, `--max-depth N`
limits the walk. `vhdpeek --help` lists everything.

Diagnostics go to stderr, so `--cat` is byte-exact and pipeable into
`sha256sum`, `tar` or `qemu-system-x86_64 -kernel`. Bad input is reported
rather than raised — `error: no such file: x.vhd`, a hint, and exit `2`
(`1` = opened but the request failed, `0` = success).

## GUI

```bash
vhdpeek --gui disk.vhd
```

![vhdpeek GUI](assets/gui-screenshot.png)

Opens on the partition table and stays there. Expand a partition to list it.
Expand an `.iso` and its contents appear underneath the file, in place, with
the partition still above it. Directories are read only when expanded, and
all filesystem work runs off the UI thread.

![Nested ISO](assets/gui-screenshot-iso.png)

Copy a file or folder out with `Ctrl+E`; folders are copied recursively, with
progress and cancellation. Preview shows text as text and anything else as a
hex dump. **Theme** (`Ctrl+T`) follows the desktop on first run, then
remembers your choice.

`Ctrl+O` file · `Ctrl+U` URL · `Ctrl+E` copy out · `F5` reload · `Ctrl+T` theme · `Esc` cancel

## Supported formats

| Layer | Format | Notes |
|---|---|---|
| Container | VHD fixed | data at offset 0, footer at end |
| | VHD dynamic / differencing | `cxsparse` header, BAT, sector bitmaps; one BAT entry per 2 MiB block |
| | VHDX | region table, metadata region, BAT; one entry per 1 MiB block, state in bits 0–2, file offset in MiB in bits 20–63 |
| Partition | MBR | four primaries plus the extended/logical EBR chain |
| | GPT | protective MBR, header at LBA 1, 128-byte entries |
| Filesystem | FAT12/16/32 | BPB, on-demand FAT (64-sector LRU), LFN, 8.3 case flags, FAT12 nibbles |
| | NTFS | `$MFT` with runlists and `$ATTRIBUTE_LIST`, resident/non-resident `$DATA`, `$I30` B-tree, LZNT1 |
| | ext2/3/4 | extent trees, 64-bit group descriptors, filetype dirs |
| | ISO 9660 | PVD, Joliet, Rock Ridge (SUSP incl. `CE`/`CL`/`RE`/`SK`), multi-extent files |

A read maps a virtual offset to a file offset, coalescing contiguous runs so
one run becomes one HTTP request. Holes and the tail past the virtual size read
as zeros, so the layers above never see a short read. The BAT is read a 4 KiB
page at a time, so a 60 GiB dynamic disk is never loaded wholesale.

Differencing disks and VHDX files with a parent are detected and reported
(`has_parent`, `parent_name`), but the parent chain is **not** resolved: a
block that lives in the parent reads as zeros. A VHDX whose log is not empty
sets `is_dirty` and the CLI warns — the log is not replayed.

## Performance

Measured on Windows, Python 3.14. `tools/bench.py` reproduces all of it.

**Parse cost** — open the image, read the partition table, mount the
filesystem, list the root directory:

| Image | Time |
|---|---|
| fixed VHD | 0.44 ms |
| dynamic VHD | 0.48 ms |
| VHDX | 0.71 ms |
| FAT12 / FAT16 / FAT32 | 0.44 – 0.67 ms |
| NTFS | 0.49 ms |
| ext4 | 0.45 ms |
| ISO 9660 | 0.48 ms |

**Bulk read**, local file, 4 MiB:

| Filesystem | Throughput |
|---|---|
| ISO 9660 | 3.1 GiB/s |
| ext4 | 791 MiB/s |
| NTFS | 785 MiB/s |
| FAT32 | 138 MiB/s (512-byte clusters, one lookup per cluster) |

**Over HTTP**, 60 GiB sparse VHD with an ISO inside it. Only the ranges each
operation needs are fetched; nothing is downloaded up front:

| Operation | Requests | Bytes fetched | Time |
|---|---|---|---|
| open + list `/` | 6 | 159 KB | 16 ms |
| enter the nested ISO | 2 | 64 KB | 6 ms |
| read a 2 MiB file from that ISO | 3 | 2.08 MB | 25 ms |

Request count is what a real network charges for, so the block cache trades
round trips against over-fetched bytes. `BLOCK_SIZE` (32 KiB) was picked by
measuring that tradeoff across link profiles from LAN to mobile: raising it
reduces requests but multiplies bytes.

### Verified against a real Azure blob

A 64 GiB Ubuntu 24.04.5 cloud image (`PageBlob`, GPT, SAS-token URL) was
browsed without downloading it. Session total: **23 requests, 0.92 MiB** out of
68,719,477,248 bytes — 0.0014% of the image, in 3.2 s (141 ms mean round-trip
to Azure).

| Operation | Requests | Bytes |
|---|---|---|
| open + parse GPT + mount ext4 + list `/` | 5 | 160 KiB |
| read `/etc/os-release` (needed `/etc`, a multi-block dir) | 11 | 352 KiB |
| read `/etc/hostname` (7 B) | 1 | 32 KiB |
| resolve symlink `/vmlinuz` and read 64 B | 2 | 64 KiB |
| 1 MiB slice at offset 8 MiB of a 17 MB kernel | 1 | 1 MiB |

Azure Blob serves `Range` on page blobs, so SAS-token URLs work directly.
Round-trip latency, not bandwidth, dominates: a depth-2 walk of that filesystem
cost 107 requests and 12.5 s while fetching only 3.5 MB.

## Limits

- No writes; no NTFS compression beyond LZNT1; no EFS decryption.
- Only the unnamed `$DATA` stream is exposed — alternate data streams are not.
- FAT volume labels are read, but exFAT is rejected.
- A VHDX that needs log replay may read stale data.
- No hybrid MBR handling, no APFS, no LVM, no dm-crypt.
- The HTTP server must support `Range`. If it ignores the header, reads near
  the start still work, but a late offset raises `RangeNotSupported` rather
  than downloading everything before it.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

301 tests. Fixture images are generated from the published on-disk layouts
(`tests/fixtures/`), not by the code under test, and `TestGenerators`
re-validates those bytes with independent third-party readers.

The GUI tests drive real Tk widgets and skip when no display is available. On
a headless machine:

```bash
xvfb-run -a python -m pytest tests -q
```

Regenerate the sample images in `test_data/` with
`python tools/make_test_images.py`. CI runs the suite on Python 3.9 – 3.13
across Linux, macOS and Windows, plus a CLI smoke test.



## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup
and the two rules that matter:

- **A bug fix gets a test that fails before it.** Reproduce first.
- **Fixtures come from the spec, not from the reader.** Parsing bytes you just
  wrote proves nothing.

Report security issues through [SECURITY.md](SECURITY.md) rather than the
issue tracker.


## By [ayomidelog](https://github.com/ayomidelog)
