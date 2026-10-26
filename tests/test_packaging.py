"""
Packaging: the console scripts a `pip install` creates must work.

These are easy to break silently - a renamed module or a typo in
`pyproject.toml` only shows up after an install, which the unit tests never
do. The declarations are read straight from the file and resolved to real
callables.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def read_pyproject() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def scripts() -> dict:
    """
    The `[project.scripts]` table, parsed without a TOML library.

    `tomllib` is 3.11+, and the suite has to run on 3.9, so this reads the one
    table it needs rather than adding a dependency.
    """
    text = read_pyproject()
    match = re.search(r"^\[project\.scripts\]\s*$(.*?)(?=^\[|\Z)",
                      text, re.M | re.S)
    assert match, "pyproject.toml has no [project.scripts] table"
    found = {}
    for line in match.group(1).splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        name, _, target = line.partition("=")
        found[name.strip().strip('"')] = target.strip().strip('"')
    return found


class TestProjectMetadata:
    def test_name_and_version(self):
        text = read_pyproject()
        assert re.search(r'^name = "vhdpeek"$', text, re.M)
        assert re.search(r'^version = "\d+\.\d+\.\d+"$', text, re.M)

    def test_python_floor_matches_the_readme(self):
        """
        The README states the floor in prose or in the badge; either is fine,
        but it must not advertise a different one from `requires-python`.
        """
        text = read_pyproject()
        match = re.search(r'^requires-python = ">=(\d+)\.(\d+)"$', text, re.M)
        assert match
        floor = f"{match.group(1)}.{match.group(2)}"

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert (f"Python {floor}+" in readme
                or f"python-{floor}" in readme), \
            f"README does not state Python {floor}"

    def test_license_is_declared(self):
        assert re.search(r'^license = \{ text = "MIT" \}$',
                         read_pyproject(), re.M)
        assert (ROOT / "LICENSE").is_file()

    def test_no_runtime_dependency_is_required(self):
        """
        Local images must work with the standard library alone, so `requests`
        belongs in an extra, never in `dependencies`.
        """
        text = read_pyproject()
        match = re.search(r"^dependencies = \[(.*?)\]", text, re.M | re.S)
        assert match
        assert match.group(1).strip() == ""
        assert "requests" in text          # ...but offered as an extra


class TestConsoleScripts:
    def test_exactly_one_command(self):
        """
        `vhdpeek --gui` covers the window, so a second `vhdpeek-gui` command
        would only be a second name for it.
        """
        assert set(scripts()) == {"vhdpeek"}

    @pytest.mark.parametrize("name", ["vhdpeek"])
    def test_target_resolves_to_a_callable(self, name):
        target = scripts()[name]
        module_name, _, attribute = target.partition(":")
        module = importlib.import_module(module_name)
        function = getattr(module, attribute)
        assert callable(function)

    def test_command_is_the_cli_main(self):
        assert scripts()["vhdpeek"] == "vhdpeek.cli:main"

    def test_the_command_reaches_the_gui(self):
        """One command has to cover both front ends."""
        from vhdpeek.cli.args import build_parser

        assert build_parser().parse_args(["--gui"]).gui is True

    def test_module_entry_point_runs_the_same_program(self):
        """`python -m vhdpeek` and the `vhdpeek` command must not diverge."""
        from vhdpeek.cli import main as command_main
        from vhdpeek.__main__ import main as module_main

        assert command_main is module_main


class TestVersionFlag:
    """`--version` must report what the package actually is."""

    def test_package_exposes_a_version(self):
        import vhdpeek

        assert vhdpeek.__version__

    def test_version_matches_pyproject(self):
        import vhdpeek

        match = re.search(r'^version = "([^"]+)"$',
                          read_pyproject(), re.M)
        assert match
        assert vhdpeek.__version__ == match.group(1)

    def test_cli_prints_it_and_exits_zero(self, capsys):
        from vhdpeek.cli import main

        with pytest.raises(SystemExit) as caught:
            main(["--version"])
        assert caught.value.code == 0

        captured = capsys.readouterr()
        import vhdpeek

        assert vhdpeek.__version__ in captured.out
        assert captured.out.strip().startswith("vhdpeek ")

    def test_version_needs_no_image(self, capsys):
        """It must work before any file or URL is named."""
        from vhdpeek.cli import main

        with pytest.raises(SystemExit) as caught:
            main(["--version"])
        assert caught.value.code == 0

    def test_the_flag_is_listed_in_help(self, capsys):
        from vhdpeek.cli import main

        with pytest.raises(SystemExit):
            main(["--help"])
        assert "--version" in capsys.readouterr().out


class TestInstallScript:
    def test_exists_and_has_a_shebang(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh")

    def test_does_not_need_git(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        assert "git clone" not in text

    def test_downloads_from_the_repository(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        assert 'REPO="ayomidelog/vhdpeek"' in text
        assert "github.com/$REPO/archive" in text

    def test_supports_uninstall(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        assert "--uninstall" in text

    def test_quotes_expansions_that_may_contain_spaces(self):
        """Unquoted paths break the moment a home directory has a space."""
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            assert "$DATA_DIR/venv/bin/python" not in stripped or '"' in stripped
