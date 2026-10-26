"""
Bad input must produce a message, not a traceback.

A wrong path, a directory, an unreachable host and a 404 are ordinary
mistakes. Each gets a `VhdPeekError` whose text names the problem, a hint, and
a distinct exit code from the CLI.
"""

from __future__ import annotations

import http.server
import threading

import pytest

from vhdpeek.core.errors import (ConnectionFailed, HttpError, NotAnImage,
                                 PathNotFound, PathNotReadable, SourceError,
                                 UnknownSize, UnsupportedScheme, VhdPeekError)
from vhdpeek.core.source import LocalSource, make_source

from tests.fixtures import vhdgen

# ---------------------------------------------------------------------------
# The hierarchy itself
# ---------------------------------------------------------------------------


class TestHierarchy:
    def test_everything_is_a_vhdpeek_error(self):
        for error in (PathNotFound, PathNotReadable, UnsupportedScheme,
                      ConnectionFailed, HttpError, UnknownSize, NotAnImage):
            assert issubclass(error, VhdPeekError)

    def test_source_errors_are_grouped(self):
        for error in (PathNotFound, PathNotReadable, UnsupportedScheme,
                      ConnectionFailed, HttpError, UnknownSize):
            assert issubclass(error, SourceError)

    def test_a_missing_image_is_not_a_source_error(self):
        """The bytes were readable; they just are not a disk image."""
        assert not issubclass(NotAnImage, SourceError)

    def test_hint_is_optional(self):
        assert VhdPeekError("boom").hint is None
        assert VhdPeekError("boom", hint="try again").hint == "try again"

    def test_describe_puts_the_hint_on_its_own_line(self):
        described = VhdPeekError("boom", hint="try again").describe()
        assert described == "boom\ntry again"

    def test_describe_without_a_hint_is_just_the_message(self):
        assert VhdPeekError("boom").describe() == "boom"

    def test_http_error_keeps_the_status(self):
        error = HttpError("nope", 404)
        assert error.status == 404
        assert str(error) == "nope"


# ---------------------------------------------------------------------------
# Local paths
# ---------------------------------------------------------------------------


class TestLocalPaths:
    def test_missing_file(self, tmp_path):
        with pytest.raises(PathNotFound) as caught:
            make_source(str(tmp_path / "nope.vhd"))
        assert "no such file" in str(caught.value)
        assert caught.value.hint

    def test_directory(self, tmp_path):
        with pytest.raises(PathNotReadable) as caught:
            make_source(str(tmp_path))
        assert "is a directory" in str(caught.value)

    def test_empty_path(self):
        with pytest.raises(PathNotFound):
            make_source("")

    def test_a_real_file_opens(self, tmp_path):
        path = tmp_path / "disk.vhd"
        path.write_bytes(vhdgen.wrap_fixed_vhd(b"\x00" * 4096))
        source = make_source(str(path))
        try:
            assert isinstance(source, LocalSource)
            assert source.size == 4096 + 512
        finally:
            source.close()

    def test_home_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        (tmp_path / "disk.vhd").write_bytes(b"\x00" * 512)
        source = make_source("~/disk.vhd")
        try:
            assert source.size == 512
        finally:
            source.close()

    def test_windows_drive_letter_is_a_path_not_a_scheme(self, tmp_path):
        """`C:\\x.vhd` parses as scheme "c"; it must not be rejected."""
        path = tmp_path / "disk.vhd"
        path.write_bytes(b"\x00" * 512)
        # The same shape as a drive path, but a real file: the one-letter
        # scheme must not be mistaken for a protocol.
        with pytest.raises(PathNotFound):
            make_source("c:/definitely/not/here.vhd")


class TestSchemes:
    @pytest.mark.parametrize("url", [
        "ftp://host/disk.vhd",
        "smb://host/share/disk.vhd",
        "s3://bucket/disk.vhd",
    ])
    def test_unsupported_scheme(self, url):
        with pytest.raises(UnsupportedScheme) as caught:
            make_source(url)
        assert "only http(s)" in caught.value.hint

    def test_file_url_is_a_local_path(self, tmp_path):
        path = tmp_path / "disk.vhd"
        path.write_bytes(b"\x00" * 512)
        source = make_source(path.as_uri())
        try:
            assert source.size == 512
        finally:
            source.close()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class _StatusServer(http.server.BaseHTTPRequestHandler):
    """Answers with whatever status the path names."""

    def log_message(self, *args):
        pass

    def _respond(self):
        name = self.path.strip("/").split(".")[0]
        codes = {"401": 401, "403": 403, "404": 404, "500": 500, "503": 503}
        if name == "nolength":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"0\r\n\r\n")
            return
        code = codes.get(name, 404)
        self.send_response(code)
        self.end_headers()

    do_GET = _respond
    do_HEAD = _respond


@pytest.fixture(scope="module")
def status_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                             _StatusServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("path,error,expected", [
    ("/404.vhd", HttpError, "no such file"),
    ("/401.vhd", HttpError, "requires authentication"),
    ("/403.vhd", HttpError, "denied"),
    ("/500.vhd", HttpError, "failed"),
    ("/503.vhd", HttpError, "failed"),
])
def test_http_status_is_named(status_server, path, error, expected):
    with pytest.raises(error) as caught:
        make_source(status_server + path)
    assert expected in str(caught.value)
    assert caught.value.status in (401, 403, 404, 500, 503)
    assert caught.value.hint


def test_a_chunked_response_cannot_be_browsed(status_server):
    """No length and no range: say so, rather than guessing."""
    with pytest.raises(UnknownSize) as caught:
        make_source(status_server + "/nolength.vhd")
    assert "did not report the image size" in str(caught.value)
    assert "Content-Length" in caught.value.hint


def test_unreachable_host_is_reported_as_such():
    """
    The failure must not be disguised as "the server gave no size".

    Port 1 on loopback refuses instantly, so this needs no network access.
    """
    with pytest.raises(ConnectionFailed) as caught:
        make_source("http://127.0.0.1:1/disk.vhd")
    assert "cannot reach" in str(caught.value)
    assert "127.0.0.1:1" in str(caught.value)
    assert caught.value.hint


def test_unresolvable_host_is_reported_as_such():
    with pytest.raises(ConnectionFailed) as caught:
        make_source("http://does-not-exist.invalid/disk.vhd")
    assert "cannot reach" in str(caught.value)


# ---------------------------------------------------------------------------
# The CLI turns these into a message and an exit code
# ---------------------------------------------------------------------------


class TestCliReporting:
    def run(self, capsys, *argv):
        from vhdpeek.cli import main

        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    def test_missing_path(self, capsys, tmp_path):
        code, out, err = self.run(capsys, str(tmp_path / "nope.vhd"))
        assert code == 2
        assert "error: no such file" in err
        assert "hint:" in err
        assert "Traceback" not in err
        assert out == ""

    def test_directory(self, capsys, tmp_path):
        code, _out, err = self.run(capsys, str(tmp_path))
        assert code == 2
        assert "is a directory" in err
        assert "Traceback" not in err

    def test_unsupported_scheme(self, capsys):
        code, _out, err = self.run(capsys, "ftp://host/disk.vhd")
        assert code == 2
        assert "cannot read ftp:// URLs" in err
        assert "Traceback" not in err

    def test_unreachable_host(self, capsys):
        code, _out, err = self.run(capsys, "http://127.0.0.1:1/disk.vhd")
        assert code == 2
        assert "cannot reach" in err
        assert "Traceback" not in err

    def test_not_an_image(self, capsys, tmp_path):
        path = tmp_path / "notes.txt"
        # Over the 512-byte minimum, so this reaches the signature check
        # rather than being rejected for size.
        path.write_bytes(b"just some text, not a disk\n" * 40)
        code, _out, err = self.run(capsys, str(path))
        assert code == 2
        assert "not a VHD or VHDX" in err
        assert "Traceback" not in err

    def test_a_good_image_still_exits_zero(self, capsys, tmp_path):
        path = tmp_path / "disk.vhd"
        path.write_bytes(vhdgen.wrap_fixed_vhd(
            vhdgen.assemble_disk(b"\x00" * (64 * 512), "mbr", 1)))
        code, _out, err = self.run(capsys, str(path), "--parts")
        assert code == 0
        assert "Partitions" in err


# ---------------------------------------------------------------------------
# The GUI reports the same text in its status bar
# ---------------------------------------------------------------------------


def test_gui_shows_the_error_text(app, tmp_path):
    """The status bar must carry the message, not "<Type>: <repr>"."""
    pytest.importorskip("tkinter")
    from tests.gui_support import wait_idle

    app.open_path(str(tmp_path / "nope.vhd"))
    wait_idle(app)

    status = app.status_label.cget("text")
    assert "no such file" in status
    assert "PathNotFound" not in status
    assert "Traceback" not in status


def test_gui_leaves_the_window_usable_after_a_failure(app, tmp_path):
    pytest.importorskip("tkinter")
    from tests.gui_support import wait_idle

    app.open_path(str(tmp_path / "nope.vhd"))
    wait_idle(app)

    # The app must not be stuck "busy" after a failed open.
    assert not app.background.busy
    assert app.session.image is None
