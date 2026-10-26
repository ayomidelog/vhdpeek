# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-26

First release with a packaged distribution. Everything below builds on 0.1.0,
which was the state of the tool before it had an installer or a binary.

### Added

- **A portable Windows executable.** One windowed binary, `vhdpeek.exe`: no
  Python required, no console window behind the app. Attached to the release
  both bare and zipped.
- **`install.sh`**, a one-line installer for Linux and macOS that puts the
  `vhdpeek` command in `~/.local/bin` without touching the system Python, and
  uninstalls with `--uninstall`.
- **`pyproject.toml`**, so `pip install .` provides the `vhdpeek` command.
  There is one command; `--gui` opens the window.
- **Dark theme**, with a Theme button and `Ctrl+T`. The window follows the
  desktop preference on first run and remembers the choice afterwards;
  `--theme dark|light` forces a scheme.
- **A release workflow** triggered by a `vX.Y.Z` tag. It validates the tag
  against `pyproject.toml` and the changelog, runs the test suite on the tag,
  builds the exe plus sdist and wheel, and creates the GitHub release with the
  changelog section as its notes. GitHub only - no external package index.
- **`tools/release.py`**, so those checks run before tagging rather than only
  in CI.
- **The app icon**, generated from `assets/vhd_ico.png` by `tools/make_icon.py`
  and embedded in the executable. All images live under `assets/`.

### Changed

- **One executable, not two.** The console build is gone: a windowed exe has
  no stdout, so it could never have offered `--cat` anyway. The command line
  stays available through `pip install` and `install.sh`.
- **Bad input is reported, not raised.** A missing file, a directory, an
  unsupported scheme, an unreachable host and every HTTP error now produce a
  message with a hint and exit code 2, instead of a traceback. Previously a
  refused connection and a 404 both surfaced as "the server did not report
  Content-Length", which pointed at the wrong problem.
- `detect_and_parse` raises `NotAnImage` / `UnknownSize` rather than
  `ValueError`, and names the first bytes it saw.
- The GUI tests skip on macOS CI, where Tk blocks waiting for a window server
  instead of raising, and both CI jobs carry a timeout.

### Fixed

- The **Open URL** dialog opened in the screen's top-left corner. It is now
  centred over the window that raised it, clamped to stay on screen.
- The placeholder tree id contained a NUL byte, which Tcl truncates on
  Python <= 3.11: populating a partition raised `Item ... already exists`.
- The preview used "Consolas" unconditionally, so off Windows it fell back to
  a proportional font and the hex dump stopped lining up.
- `file://` URLs with a Windows drive letter lost the drive.
- `vhdpeek.exe --help` opened the window and then reported that no such file
  existed, because `--help` was taken for a filename.
- Building the four-partition test fixture held several copies of a 200 MiB
  disk at once, failing on a machine under memory pressure.

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

[Unreleased]: https://github.com/ayomidelog/vhdpeek/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ayomidelog/vhdpeek/releases/tag/v1.0.0
[0.1.0]: https://github.com/ayomidelog/vhdpeek/releases/tag/v0.1.0
