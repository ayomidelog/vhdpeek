"""Shared helpers for building filesystem images."""

from __future__ import annotations

from typing import Dict, List, Tuple

def _tree(files: Dict[str, bytes]) -> dict:
    """{"a/b.txt": b"..", "c/": b""} -> nested dict tree."""
    root = {"dir": True, "children": {}}
    for path, data in files.items():
        parts = [p for p in path.split("/") if p]
        if not parts:
            continue
        node = root
        for part in parts[:-1]:
            node = node["children"].setdefault(
                part, {"dir": True, "children": {}})
        if path.endswith("/"):
            node["children"].setdefault(
                parts[-1], {"dir": True, "children": {}})
        else:
            node["children"][parts[-1]] = {"dir": False, "data": data}
    return root


def _walk_dirs(tree: dict) -> List[Tuple[str, dict]]:
    out = [("", tree)]
    queue = [("", tree)]
    while queue:
        prefix, node = queue.pop(0)
        for name, child in sorted(node["children"].items()):
            if child["dir"]:
                path = f"{prefix}/{name}" if prefix else name
                out.append((path, child))
                queue.append((path, child))
    return out


def _walk_files(tree: dict) -> List[Tuple[str, dict]]:
    out: List[Tuple[str, dict]] = []

    def walk(prefix: str, node: dict) -> None:
        for name, child in sorted(node["children"].items()):
            path = f"{prefix}/{name}" if prefix else name
            if child["dir"]:
                walk(path, child)
            else:
                out.append((path, child))

    walk("", tree)
    return out


def _parent_path(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""
