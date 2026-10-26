# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-26

First documented release. Everything below already worked before this date;
this entry records the state it was in, so later changes have something to
diff against.

### Added

- Browsing of VHD (fixed, dynamic, differencing) and VHDX containers, with the
  BAT read a 4 KiB page at a time and holes zero-filled, so a 60 GiB sparse
  image is never loaded wholesale.
- HTTP and HTTPS sources using `Range` requests with a block cache. A server
  that ignores `Range` raises `RangeNotSupported` instead of downloading the
  image.
- MBR (including the extended/logical EBR chain) and GPT partition tables.
- Filesystem readers: FAT12/16/32 (LFN, on-demand FAT), NTFS (`$MFT` with
  runlists, `$I30` B-tree, LZNT1), ext2/3/4 (extent trees, 64-bit group
  descriptors), and ISO 9660 (Joliet, Rock Ridge, multi-extent).
- Nested ISO support: an `.iso` inside a filesystem is mounted in place
  without extraction, because every reader takes a `ByteView`.
- CLI: `--parts`, `--part`, `--tree`, `--max-depth`, `--ls`, `--cat`, `--iso`,
  `--fs`. Diagnostics go to stderr, so `--cat` streams byte-exact.
- Tk explorer that opens on the partition table, expands lazily, nests an ISO
  under the file that holds it, previews text or hex, and copies files and
  folders out recursively with progress and cancellation.
- Test suite of 171 tests, with image generators built from the published
  on-disk layouts and cross-checked against independent third-party readers.
- `tools/bench.py`, `tools/make_test_images.py` and
  `tools/make_ubuntu_image.py` for measurement and demo images.

### Changed

- **Renamed from `vhdurl` to `vhdpeek`.** The package, the module path
  (`python -m vhdpeek`), and the CLI `prog` name all moved. Anything importing
  `vhdurl.*` must switch to `vhdpeek.*`.
- Split the flat modules into packages: `core/`, `fs/`, `session/`, `gui/`,
  `cli/`. No module is over 400 lines, and the layers only call downwards.
- Tests reorganised to one module per area under `tests/`.
- Generated images are gitignored build products rather than committed files.

### Fixed

- A malformed keyword argument made the GUI fail on construction.
- Small images reported their size as `0.0 MiB`.

[Unreleased]: https://github.com/ayomidelog/vhdpeek/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ayomidelog/vhdpeek/releases/tag/v0.1.0
