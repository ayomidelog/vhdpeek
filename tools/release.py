"""
Release preparation: version consistency and release notes.

A tag that disagrees with `pyproject.toml`, or a version with no changelog
entry, is the kind of mistake that only shows up after publishing - when it
cannot be taken back. Both are checked here, where they can be tested.

    python tools/release.py check --tag v0.1.0
    python tools/release.py notes --version 0.1.0 --out notes.md

Exit code is 0 on success and 1 on a problem, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"

_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.M)
_HEADING = re.compile(r"^##\s+(.*)$", re.M)
_TAG = re.compile(r"^v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?)$")


class ReleaseError(Exception):
    """A problem that should stop the release."""


def project_version() -> str:
    """The version declared in `pyproject.toml`."""
    match = _VERSION.search(PYPROJECT.read_text(encoding="utf-8"))
    if not match:
        raise ReleaseError(f"no version found in {PYPROJECT.name}")
    return match.group(1)


def tag_version(tag: str) -> str:
    """`v0.1.0` or `0.1.0` -> `0.1.0`."""
    match = _TAG.match(tag.strip())
    if not match:
        raise ReleaseError(
            f"{tag!r} is not a version tag; expected vMAJOR.MINOR.PATCH")
    return match.group(1)


def check_tag(tag: str) -> str:
    """
    Confirm the tag matches the project version, and return that version.

    Publishing a tag that disagrees with the metadata produces a release
    whose assets and files claim different versions.
    """
    from_tag = tag_version(tag)
    declared = project_version()
    if from_tag != declared:
        raise ReleaseError(
            f"tag {tag} says {from_tag}, but pyproject.toml says {declared}"
            f"\n  bump the version, or tag {declared} instead")
    return declared


def sections(text: str) -> dict:
    """
    Map heading text -> body, for every `## ` heading in a changelog.

    Kept deliberately small: a full Markdown parser would be more to trust
    than the format it is reading.
    """
    headings = list(_HEADING.finditer(text))
    found = {}
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        found[match.group(1).strip()] = text[match.end():end].strip()
    return found


def release_notes(version: str, text: Optional[str] = None) -> str:
    """
    The changelog section for `version`, without the heading itself.

    A release with no notes is a release nobody can evaluate, so a missing
    section is an error rather than an empty body.
    """
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    found = sections(text)

    for heading, body in found.items():
        # Headings look like "[0.1.0] - 2026-10-26" or "0.1.0".
        name = heading.strip("[]").split("]")[0].split(" - ")[0].strip()
        name = name.strip("[]").strip()
        if name == version:
            if not body:
                raise ReleaseError(f"the {version} changelog section is empty")
            return unwrap(body)

    known = ", ".join(sorted(found)) or "none"
    raise ReleaseError(
        f"CHANGELOG.md has no section for {version} (found: {known})"
        f"\n  add '## [{version}] - YYYY-MM-DD' with what changed")


def unwrap(text: str) -> str:
    """
    Join hard-wrapped prose so the release body has one line per paragraph.

    The changelog is wrapped to fit an 80-column editor; a release page is
    rendered by the browser, where those breaks show up as ragged lines in the
    middle of a sentence. Markdown structure is preserved:

      * blank lines, headings, list markers, tables and code fences are kept
      * a continuation line is joined onto the previous one with a space
      * list items keep their own line, and their continuations join them
      * fenced code blocks are left exactly as written
    """
    out = []
    in_fence = False
    previous_open = False      # the previous line can absorb a continuation

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            previous_open = False
            continue

        if in_fence:
            out.append(line)
            continue

        if not stripped:
            out.append("")
            previous_open = False
            continue

        if stripped.startswith(("#", "|")):
            out.append(line)
            previous_open = False
            continue

        if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\. ", stripped):
            out.append(line)
            previous_open = True
            continue

        if previous_open and out:
            # A continuation: append to the line above.
            out[-1] = out[-1].rstrip() + " " + stripped
        else:
            out.append(line)
            previous_open = True

    # Collapse runs of blank lines left behind.
    result = []
    for line in out:
        if line == "" and result and result[-1] == "":
            continue
        result.append(line)
    return "\n".join(result).strip("\n")


def unreleased_body(text: Optional[str] = None) -> str:
    """What is still under `## [Unreleased]`."""
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    return sections(text).get("[Unreleased]", "")


def unreleased_entries(version: str, text: Optional[str] = None) -> str:
    """
    A warning when `[Unreleased]` still holds entries, else "".

    Not an error by default: the notes come from the version's own section,
    so they are still correct. But an `[Unreleased]` that was never renamed
    usually means the version's section is missing the newest changes.
    """
    body = unreleased_body(text)
    if not body:
        return ""
    return (f"[Unreleased] still has entries while {version} is being "
            f"released\n  if those belong in {version}, rename the heading to "
            f"'## [{version}] - <today>' first")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release.py",
        description="Check a release tag and extract its notes.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="verify the tag matches the project")
    check.add_argument("--tag", required=True)
    check.add_argument("--strict", action="store_true",
                       help="treat a non-empty [Unreleased] as an error")

    notes = sub.add_parser("notes", help="write the release notes")
    notes.add_argument("--version", required=True)
    notes.add_argument("--out", default="-",
                       help="file to write, or - for stdout")

    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            version = check_tag(args.tag)
            release_notes(version)          # fail now if it is missing

            warning = unreleased_entries(version)
            if warning:
                if args.strict:
                    raise ReleaseError(warning)
                print(f"warning: {warning}", file=sys.stderr)

            print(f"ok: tag {args.tag} matches version {version}")

        else:
            body = release_notes(args.version)
            if args.out == "-":
                print(body)
            else:
                Path(args.out).write_text(body + "\n", encoding="utf-8",
                                          newline="\n")
                print(f"wrote {args.out}")
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
