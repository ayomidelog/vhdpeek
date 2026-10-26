# Contributing

Thanks for taking the time to contribute.

## Setup

```bash
git clone <your-fork>
cd vhdpeek

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install -r requirements-dev.txt
python -m pytest tests -q
```

`requirements-dev.txt` pulls in `pytest`, `requests` (for the HTTP tests) and
the optional independent readers that `tests/test_generators.py` cross-checks
the fixtures against. Everything else is standard library.

Generate the sample images used by the CLI examples with:

```bash
python tools/make_test_images.py
```

They land in `test_data/`, which is gitignored.

## What to work on

The [limits](README.md#limits) section is an honest list of what is missing —
it is the best place to find something useful to do. If you plan a large
change, open an issue first so the design can be agreed before the code.

## Tests

Two rules:

- **Every bug fix gets a test that fails before it.** Reproduce first; a fix
  without a failing case is a guess.
- **Fixtures come from the spec, not from the reader.** Image generators in
  `tests/fixtures/` build bytes from the published on-disk layouts. Parsing
  what you just wrote proves nothing; `tests/test_generators.py` validates
  those bytes with independent third-party readers.

Run the suite before opening a pull request:

```bash
python -m pytest tests -q
```

The GUI tests drive real Tk widgets and skip when no display is available.
On a headless machine:

```bash
xvfb-run -a python -m pytest tests -q
```

## Style

- **One job per module, and no module over 400 lines.** If a file is growing
  past that, the concern inside it is probably two concerns.
- **Layers only call downwards.** `core` → `fs` → `session` → `cli`/`gui`.
  A filesystem reader must never import `session` or `gui`.
- **A filesystem reader takes a `ByteView`, nothing else.** That is what keeps
  every parser testable against a plain `bytes` object and makes nesting an
  ISO inside ext4 a one-liner.
- **Standard library first.** `requests` is the only runtime dependency, and
  only for `http(s)` sources.
- Type hints on public functions, `from __future__ import annotations` at the
  top. Lines under 80 columns where it does not hurt readability.
- Comments explain *why*, not *what*. `# skip the sector bitmap` earns its
  place; `# loop over entries` does not.

Keep the diff focused: a bug fix should not carry an unrelated reformat.

## Pull requests

1. One logical change per pull request.
2. Tests pass locally, and new behaviour has a test.
3. `python -m pyflakes vhdpeek tests tools` is clean.
4. If behaviour or the public surface changed, update `README.md` and add an
   entry under `## [Unreleased]` in `CHANGELOG.md`.

CI runs the suite on Python 3.9 – 3.13 across Linux, macOS and Windows; a red
run needs fixing before merge.

## Reporting bugs

Include the output of:

```bash
python -m vhdpeek --help
python -m vhdpeek <image> --parts
```

plus the container type, the filesystem, and what you expected to see. If the
image is remote and public, the URL helps; if it is private, describe its
shape instead (GPT with four partitions, ext4 root, and so on). Never paste a
live SAS token or other credential — see [SECURITY.md](SECURITY.md).
