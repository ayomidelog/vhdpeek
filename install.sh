#!/bin/sh
#
# Install vhdpeek without cloning it.
#
#   curl -fsSL https://raw.githubusercontent.com/ayomidelog/vhdpeek/main/install.sh | sh
#
# Downloads the source archive, installs it into a private virtual environment
# and links `vhdpeek` into ~/.local/bin. Nothing else on the system is touched,
# and uninstalling is `install.sh --uninstall`.
#
# Options (or the matching environment variable):
#   --ref REF        branch or tag to install     (VHDPEEK_REF, default: main)
#   --prefix DIR     where to link the command    (VHDPEEK_PREFIX, default: ~/.local)
#   --uninstall      remove the environment and the links
#   --help
#
set -eu

REPO="ayomidelog/vhdpeek"
REF="${VHDPEEK_REF:-main}"
PREFIX="${VHDPEEK_PREFIX:-$HOME/.local}"
UNINSTALL=0

say()  { printf '%s\n' "$*"; }
die()  { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Install vhdpeek without cloning it.

    curl -fsSL https://raw.githubusercontent.com/ayomidelog/vhdpeek/main/install.sh | sh

Options:
    --ref REF        branch or tag to install (default: main)
    --prefix DIR     where to link the command (default: ~/.local)
    --uninstall      remove the environment and the links
    --help

Environment:
    VHDPEEK_REF      same as --ref
    VHDPEEK_PREFIX   same as --prefix
    VHDPEEK_ARCHIVE  override the download URL (mirrors, offline installs)
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --ref)       [ $# -ge 2 ] || die "--ref needs a value"; REF="$2"; shift 2 ;;
        --prefix)    [ $# -ge 2 ] || die "--prefix needs a value"; PREFIX="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "unknown option: $1 (try --help)" ;;
    esac
done

BIN_DIR="$PREFIX/bin"
# Everything lives under --prefix, so installing to /opt or /usr/local moves
# the environment too, and --uninstall cleans up exactly one tree.
DATA_DIR="$PREFIX/share/vhdpeek"

# --- uninstall ------------------------------------------------------------

if [ "$UNINSTALL" -eq 1 ]; then
    rm -f "$BIN_DIR/vhdpeek" "$BIN_DIR/vhdpeek.exe"
    rm -rf "$DATA_DIR"
    say "Removed vhdpeek from $BIN_DIR and $DATA_DIR"
    exit 0
fi

# --- prerequisites --------------------------------------------------------

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || die "Python 3.9 or newer is required (python3 not found, or too old)"

if command -v curl >/dev/null 2>&1; then
    FETCH="curl -fsSL"
elif command -v wget >/dev/null 2>&1; then
    FETCH="wget -qO-"
else
    FETCH=""
fi

# --- download -------------------------------------------------------------

if [ -n "${VHDPEEK_ARCHIVE:-}" ]; then
    ARCHIVE="$VHDPEEK_ARCHIVE"
else
    case "$REF" in
        v[0-9]*) ARCHIVE="https://github.com/$REPO/archive/refs/tags/$REF.tar.gz" ;;
        *)       ARCHIVE="https://github.com/$REPO/archive/refs/heads/$REF.tar.gz" ;;
    esac
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM

say "Fetching $REF ..."
if [ -f "$ARCHIVE" ]; then
    # A local tarball: useful for mirrors, offline installs and tests.
    cp "$ARCHIVE" "$TMP/src.tar.gz" || die "could not read $ARCHIVE"
else
    [ -n "$FETCH" ] || die "curl or wget is required to download $ARCHIVE"
    # shellcheck disable=SC2086
    $FETCH "$ARCHIVE" > "$TMP/src.tar.gz" || die "could not download $ARCHIVE"
fi
tar -xzf "$TMP/src.tar.gz" -C "$TMP" || die "could not unpack the archive"

SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -n "$SRC" ] && [ -f "$SRC/pyproject.toml" ] || die "archive did not contain the project"

# --- install --------------------------------------------------------------

say "Installing into $DATA_DIR ..."
mkdir -p "$DATA_DIR"
"$PYTHON" -m venv --clear "$DATA_DIR/venv" || die "could not create a virtual environment"

# `bin` on POSIX, `Scripts` on Windows - the script also runs under Git Bash.
VENV_BIN="$DATA_DIR/venv/bin"
[ -d "$VENV_BIN" ] || VENV_BIN="$DATA_DIR/venv/Scripts"
[ -x "$VENV_BIN/python" ] || [ -x "$VENV_BIN/python.exe" ] \
    || die "virtual environment has no interpreter"

PY="$VENV_BIN/python"
[ -x "$PY" ] || PY="$VENV_BIN/python.exe"

# Installed in two steps: pip parses "/path/to/dir[extra]" as a requirement
# name rather than a path, so the extra is passed as its own requirement.
"$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$PY" -m pip install --quiet "$SRC" || die "pip install failed"
"$PY" -m pip install --quiet requests || die "could not install requests"

mkdir -p "$BIN_DIR"
# `.exe` first: MSYS resolves an extensionless path to it, which would
# otherwise pick a name that does not exist on disk.
src="$VENV_BIN/vhdpeek.exe"
[ -e "$src" ] || src="$VENV_BIN/vhdpeek"

COMMAND=""
if [ -e "$src" ]; then
    # Keep the real basename: on Windows the command is vhdpeek.exe, and a
    # copy without the suffix would not run.
    COMMAND="$BIN_DIR/${src##*/}"
    rm -f "$COMMAND"
    ln -sf "$src" "$COMMAND" 2>/dev/null || cp "$src" "$COMMAND"
fi
[ -n "$COMMAND" ] || die "the package did not install a vhdpeek command"

say ""
"$COMMAND" --help >/dev/null 2>&1 \
    || die "installed, but '$COMMAND --help' failed"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) say "Add $BIN_DIR to your PATH to run 'vhdpeek' from any shell:"
       say ""
       say "    export PATH=\"$BIN_DIR:\$PATH\""
       say "" ;;
esac

say "Installed. Try:"
say ""
say "    vhdpeek disk.vhd --parts"
say "    vhdpeek https://example.com/disk.vhdx --ls /etc"
say "    vhdpeek --gui disk.vhd"
