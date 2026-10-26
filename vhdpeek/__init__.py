"""vhdpeek — browse VHD/VHDX images over HTTP or locally, without mounting."""

from __future__ import annotations

__all__ = ["__version__"]


def _version() -> str:
    """
    The installed version, falling back to the source tree.

    Installed builds read the metadata that `pip` wrote; a checkout has no
    metadata, so `pyproject.toml` is read instead. One of the two always
    exists, and neither can drift from the other because a release reads the
    same file.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("vhdpeek")
        except PackageNotFoundError:
            pass
    except ImportError:                   # pragma: no cover - 3.7 and older
        pass

    try:
        import re
        from pathlib import Path

        text = (Path(__file__).resolve().parent.parent
                / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        if match:
            return match.group(1)
    except OSError:
        pass

    return "unknown"


__version__ = _version()
