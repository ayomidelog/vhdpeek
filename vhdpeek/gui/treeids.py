"""
Tree item identifiers.

A tree id encodes the scope it belongs to: `<scope>\\x1f<path>`. That is what
lets a partition and an ISO mounted inside it live in one tree without their
paths colliding.
"""

from __future__ import annotations

from typing import Tuple

SEP = "\x1f"
PLACEHOLDER = "\x00more"


def split_iid(iid: str) -> Tuple[str, str]:
    """Tree id -> (scope, path)."""
    if SEP not in iid:
        return iid, ""
    scope, _, path = iid.partition(SEP)
    return scope, path


def make_iid(scope: str, path: str) -> str:
    return f"{scope}{SEP}{path}"
