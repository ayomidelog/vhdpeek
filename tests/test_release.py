"""
Release preparation: the checks that must pass before a tag is published.

A tag that disagrees with `pyproject.toml`, or a version with no changelog
section, produces a release nobody can evaluate - and it cannot be taken back
once it is up. These tests pin the rules.
"""

from __future__ import annotations

import pytest

from tools import release


CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.0] - 2026-01-01

### Added

- a thing.

### Fixed

- another thing.

## [1.1.0] - 2025-12-01

- older.
"""


class TestVersionParsing:
    @pytest.mark.parametrize("tag,expected", [
        ("v1.2.0", "1.2.0"),
        ("1.2.0", "1.2.0"),
        ("v0.1.0", "0.1.0"),
        ("v1.2.3-rc1", "1.2.3-rc1"),
        ("  v1.2.0  ", "1.2.0"),
    ])
    def test_accepts_a_version_tag(self, tag, expected):
        assert release.tag_version(tag) == expected

    @pytest.mark.parametrize("tag", ["v1.2", "release-1", "v1", "", "latest"])
    def test_rejects_anything_else(self, tag):
        with pytest.raises(release.ReleaseError):
            release.tag_version(tag)

    def test_project_version_is_read_from_pyproject(self):
        version = release.project_version()
        assert version.count(".") == 2


class TestTagMatchesProject:
    def test_a_matching_tag_passes(self):
        version = release.project_version()
        assert release.check_tag(f"v{version}") == version

    def test_a_mismatched_tag_is_an_error(self):
        with pytest.raises(release.ReleaseError) as caught:
            release.check_tag("v99.0.0")
        message = str(caught.value)
        assert "99.0.0" in message
        assert release.project_version() in message
        assert "bump the version" in message


class TestSections:
    def test_every_heading_is_found(self):
        found = release.sections(CHANGELOG)
        assert "[Unreleased]" in found
        assert "[1.2.0] - 2026-01-01" in found
        assert "[1.1.0] - 2025-12-01" in found

    def test_a_section_body_stops_at_the_next_heading(self):
        found = release.sections(CHANGELOG)
        body = found["[1.1.0] - 2025-12-01"]
        assert "older." in body
        assert "another thing" not in body

    def test_the_last_section_runs_to_the_end(self):
        found = release.sections("## [1.0.0]\n\ntail\n")
        assert "tail" in found["[1.0.0]"]


class TestReleaseNotes:
    def test_notes_for_a_version(self):
        notes = release.release_notes("1.2.0", CHANGELOG)
        assert "a thing" in notes
        assert "another thing" in notes
        assert "older" not in notes

    def test_the_heading_is_not_included(self):
        notes = release.release_notes("1.2.0", CHANGELOG)
        assert not notes.startswith("## ")

    def test_a_missing_version_lists_what_exists(self):
        with pytest.raises(release.ReleaseError) as caught:
            release.release_notes("9.9.9", CHANGELOG)
        message = str(caught.value)
        assert "9.9.9" in message
        assert "1.2.0" in message        # so the typo is obvious

    def test_an_empty_section_is_an_error(self):
        with pytest.raises(release.ReleaseError, match="empty"):
            release.release_notes("1.2.0", "## [1.2.0]\n\n## [1.1.0]\n\n- x\n")

    def test_the_real_changelog_has_the_current_version(self):
        """The repo itself must be releasable."""
        notes = release.release_notes(release.project_version())
        assert notes.strip()


class TestUnreleased:
    def test_entries_under_unreleased_are_reported(self):
        warning = release.unreleased_entries(
            "1.2.0", "## [Unreleased]\n\n- wip\n\n## [1.2.0]\n\n- done\n")
        assert "Unreleased" in warning
        assert "1.2.0" in warning

    def test_an_empty_unreleased_is_quiet(self):
        assert release.unreleased_entries(
            "1.2.0", "## [Unreleased]\n\n## [1.2.0]\n\n- done\n") == ""

    def test_the_real_changelog_is_quiet_or_explains_itself(self):
        warning = release.unreleased_entries(release.project_version())
        assert warning == "" or "Unreleased" in warning


class TestCommandLine:
    def test_check_passes_for_the_current_version(self, capsys):
        code = release.main(["check", "--tag",
                             f"v{release.project_version()}"])
        captured = capsys.readouterr()
        assert code == 0
        assert "ok:" in captured.out

    def test_check_fails_for_a_mismatched_tag(self, capsys):
        code = release.main(["check", "--tag", "v99.0.0"])
        captured = capsys.readouterr()
        assert code == 1
        assert "error:" in captured.err

    def test_notes_go_to_a_file(self, tmp_path, capsys):
        target = tmp_path / "notes.md"
        code = release.main(["notes", "--version",
                             release.project_version(),
                             "--out", str(target)])
        assert code == 0
        assert target.is_file()
        assert target.read_text(encoding="utf-8").strip()

    def test_notes_default_to_stdout(self, capsys):
        code = release.main(["notes", "--version", release.project_version()])
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip()


class TestWorkflows:
    """The release pipeline must stay consistent with the tooling."""

    def workflow(self, name):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        return (root / ".github" / "workflows" / name).read_text(
            encoding="utf-8")

    def test_a_release_workflow_exists(self):
        assert self.workflow("release.yml")

    def test_it_triggers_on_a_version_tag(self):
        text = self.workflow("release.yml")
        assert 'tags: ["v*"]' in text

    def test_it_validates_before_publishing(self):
        text = self.workflow("release.yml")
        assert "tools/release.py check" in text
        # The publish job must wait for the checks.
        publish = text.split("publish:")[1]
        assert "needs:" in publish

    def test_it_publishes_to_github_only(self):
        text = self.workflow("release.yml")
        assert "gh release create" in text
        for external in ("pypi", "twine upload", "PYPI_API_TOKEN"):
            assert external not in text.lower().replace("twine check", "")

    def test_it_uses_the_notes_from_the_changelog(self):
        text = self.workflow("release.yml")
        assert "tools/release.py notes" in text
        assert "--notes-file" in text

    def test_the_test_workflow_is_reusable(self):
        """release.yml calls it, so it must accept workflow_call."""
        assert "workflow_call:" in self.workflow("tests.yml")

    def test_the_build_workflow_is_reusable(self):
        assert "workflow_call:" in self.workflow("build-exe.yml")

    def test_the_build_workflow_no_longer_creates_releases(self):
        """One owner for release creation: release.yml."""
        text = self.workflow("build-exe.yml")
        assert "gh release" not in text
