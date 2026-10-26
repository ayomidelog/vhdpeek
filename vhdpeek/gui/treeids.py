"""
Tree item identifiers.

A tree id encodes the scope it belongs to: `<scope>\\x1f<path>`. That is what
lets a partition and an ISO mounted inside it live in one tree without their
paths colliding.
"""

from __future__ import annotations

from typing import Tuple

SEP = "\x1f"

# Marks a node that has not been listed yet ("loading…"). It must not contain
# a NUL byte: Tcl truncates strings at NUL on Python <= 3.11, which collapsed
# this id onto its parent and raised "Item already exists" when populating.
# A leading SEP cannot collide with a real path, since paths come from
# directory entries and never contain it.
PLACEHOLDER = SEP + "more"


def split_iid(iid: str) -> Tuple[str, str]:
    """Tree id -> (scope, path)."""
    if SEP not in iid:
        return iid, ""
    scope, _, path = iid.partition(SEP)
    return scope, path


def make_iid(scope: str, path: str) -> str:
    return f"{scope}{SEP}{path}"
