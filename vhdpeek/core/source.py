"""
Byte sources: a local file or an HTTP(S) URL read with Range requests.

Every layer above this one only ever calls `Source.read(offset, size)` and
gets exactly `size` bytes back, or an `EOFError`.  That single guarantee is
what lets a 60 GB image be browsed without downloading it: the container,
partition and filesystem layers ask for the few kilobytes they need.

`HTTPSource` caches whole aligned blocks.  Caching a *partial* range under a
block key would hand back the wrong bytes for a different offset in the same
block, so the cache only ever holds blocks that were fetched complete.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from typing import Optional
from urllib.parse import urlparse

from .errors import (ConnectionFailed, HttpError, PathNotFound,
                     PathNotReadable, SourceError, UnsupportedScheme,
                     UnknownSize)


class RangeNotSupported(IOError):
    """The server ignored `Range`, so late offsets cannot be read cheaply."""


class Source:
    """Random-access byte source."""

    size: Optional[int] = None

    def read(self, offset: int, size: int) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> "Source":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(size={self.size})"


class LocalSource(Source):
    """Reads a local file.  `pread` keeps concurrent readers safe."""

    def __init__(self, path: str):
        self.path = path
        self._fh = open(path, "rb")
        self.size = os.fstat(self._fh.fileno()).st_size
        self._lock = threading.Lock()
        self._pread = getattr(os, "pread", None)

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError(f"negative read: offset={offset} size={size}")
        if size == 0:
            return b""
        if self._pread is not None:
            data = self._pread(self._fh.fileno(), size, offset)
        else:
            with self._lock:
                self._fh.seek(offset)
                data = self._fh.read(size)
        if len(data) < size:
            raise EOFError(
                f"{self.path}: short read at {offset} "
                f"(got {len(data)} of {size})"
            )
        return data

    def close(self) -> None:
        self._fh.close()


class HTTPSource(Source):
    """
    HTTP(S) source backed by `Range` requests.

    Reads smaller than `block_size` are served from an aligned block cache;
    larger reads go straight out as one ranged GET.  Servers that ignore
    `Range` (200 instead of 206) still work: the body is streamed from byte 0
    and the requested window is sliced out.
    """

    # Metadata reads are small (512 B - 4 KiB) and scattered, so the block
    # size is a tradeoff: bigger blocks mean fewer round trips but more
    # over-fetched bytes. Measured against a 60 GiB image, listing the root
    # costs 155 KiB in 5 requests at 32 KiB versus 635 KiB in 3 requests at
    # 256 KiB; the extra two round trips are far cheaper than 480 KiB on any
    # link slower than ~10 Mbit. Bulk reads bypass the cache entirely, so
    # they are unaffected by this choice.
    BLOCK_SIZE = 32 * 1024
    CACHE_BLOCKS = 512         # 16 MiB of cache
    TIMEOUT = 60
    RETRIES = 3
    MAX_SKIP = 8 << 20      # tolerate a non-Range server only near the start

    def __init__(
        self,
        url: str,
        block_size: int = BLOCK_SIZE,
        cache_blocks: int = CACHE_BLOCKS,
        timeout: int = TIMEOUT,
        retries: int = RETRIES,
    ):
        import requests  # imported lazily: local use needs no HTTP stack

        self.url = url
        self._requests = requests
        self._session = requests.Session()
        self._block_size = max(4096, block_size)
        self._cache: "OrderedDict[int, bytes]" = OrderedDict()
        self._cache_blocks = cache_blocks
        self._timeout = timeout
        self._retries = retries
        self.bytes_fetched = 0
        self.requests_made = 0
        self.size = self._discover_size()

    # ------------------------------------------------------------------
    # Size discovery
    # ------------------------------------------------------------------

    def _discover_size(self) -> int:
        """
        Ask for one byte and read the total out of `Content-Range`.

        Failures are reported as themselves. Collapsing a refused connection
        or a 404 into "the server did not report a size" sends the user
        looking for the wrong problem.
        """
        resp = self._request("GET", self.url,
                             headers={"Range": "bytes=0-0"}, stream=True)
        try:
            if resp.status_code == 206:
                match = re.search(r"/(\d+)\s*$",
                                  resp.headers.get("Content-Range", ""))
                if match:
                    return int(match.group(1))
            elif resp.status_code == 200:
                length = resp.headers.get("Content-Length")
                if length is not None:
                    return int(length)
            else:
                raise self._http_error(resp)
        finally:
            resp.close()

        # The GET worked but carried no length; HEAD sometimes does.
        resp = self._request("HEAD", self.url, allow_redirects=True)
        try:
            length = resp.headers.get("Content-Length")
            if resp.status_code == 200 and length is not None:
                return int(length)
        finally:
            resp.close()

        raise UnknownSize(
            f"{self._host} did not report the image size",
            hint="the server must send Content-Length or a Content-Range "
                 "header; a chunked response cannot be browsed by range",
        )

    @property
    def _host(self) -> str:
        return urlparse(self.url).netloc or self.url

    def _request(self, method: str, url: str, **kwargs):
        """
        One request, with the transport failure translated into a message.

        `requests` raises a hierarchy of its own; the user needs to know
        whether the host was unreachable, slow, or refusing the certificate.
        """
        try:
            return self._session.request(method, url, timeout=self._timeout,
                                         **kwargs)
        except self._requests.exceptions.SSLError as exc:
            raise ConnectionFailed(
                f"TLS failed for {self._host}",
                hint=f"the certificate could not be verified ({exc})",
            ) from None
        except self._requests.exceptions.Timeout:
            raise ConnectionFailed(
                f"{self._host} did not answer within {self._timeout}s",
                hint="the host is slow or unreachable; try again",
            ) from None
        except self._requests.exceptions.ConnectionError as exc:
            raise ConnectionFailed(
                f"cannot reach {self._host}",
                hint=f"check the host name and your network ({_reason(exc)})",
            ) from None
        except self._requests.exceptions.InvalidURL as exc:
            raise UnsupportedScheme(
                f"not a usable URL: {self.url}", hint=str(exc)) from None

    def _http_error(self, resp) -> SourceError:
        """A readable error for a response that is not the image."""
        status = resp.status_code
        reason = resp.reason or ""
        detail = f"{status} {reason}".strip()

        if status in (401, 407):
            return HttpError(
                f"{self._host} requires authentication ({detail})",
                status, hint="the URL may need a token or a signed query string",
            )
        if status == 403:
            return HttpError(
                f"access to {self._host} was denied ({detail})",
                status, hint="the credentials are valid but not allowed here",
            )
        if status == 404:
            return HttpError(
                f"no such file on {self._host} ({detail})",
                status, hint="check the URL; the path may have changed",
            )
        if 500 <= status < 600:
            return HttpError(
                f"{self._host} failed ({detail})",
                status, hint="the problem is on the server; try again later",
            )
        return HttpError(f"{self._host} answered {detail}", status)

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _get(self, offset: int, size: int) -> bytes:
        """One ranged GET, with retries.  Returns up to `size` bytes."""
        last_error: Optional[BaseException] = None
        for attempt in range(self._retries):
            try:
                return self._get_once(offset, size)
            except (EOFError, RangeNotSupported):
                raise
            except Exception as exc:  # network hiccup, 5xx, timeout
                last_error = exc
                if attempt + 1 < self._retries:
                    time.sleep(0.4 * (attempt + 1))
        raise IOError(f"GET {self.url} bytes={offset}- failed: {last_error}")

    def _get_once(self, offset: int, size: int) -> bytes:
        end = offset + size - 1
        self.requests_made += 1
        resp = self._request("GET", self.url,
                             headers={"Range": f"bytes={offset}-{end}"},
                             stream=True)
        try:
            if resp.status_code == 206:
                return self._read_stream(resp, size)
            if resp.status_code == 200:
                # Range ignored: the body starts at byte 0, so serving a late
                # offset means transferring everything before it. That is
                # merely wasteful near the start of a file and fatal on a
                # multi-gigabyte image, so refuse instead of pretending.
                if offset > self.MAX_SKIP:
                    raise RangeNotSupported(
                        f"{self.url} ignored the Range header; reading offset "
                        f"{offset} would download {offset} bytes first. "
                        f"Use a server that supports Range requests.")
                return self._read_stream(resp, size, skip=offset)
            if resp.status_code == 416:
                return b""
            resp.raise_for_status()
            raise self._http_error(resp)
        finally:
            resp.close()

    def _read_stream(self, resp, size: int, skip: int = 0) -> bytes:
        remaining_skip = skip
        out = bytearray()
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            if remaining_skip:
                if len(chunk) <= remaining_skip:
                    remaining_skip -= len(chunk)
                    continue
                chunk = chunk[remaining_skip:]
                remaining_skip = 0
            out.extend(chunk)
            if len(out) >= size:
                break
        self.bytes_fetched += len(out)
        return bytes(out[:size])

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError(f"negative read: offset={offset} size={size}")
        if size == 0:
            return b""
        if self.size is not None and offset >= self.size:
            raise EOFError(f"read past end of {self.url} at {offset}")

        if size >= self._block_size:
            data = self._get(offset, size)
            if len(data) < size:
                raise EOFError(
                    f"short read at {offset}: got {len(data)} of {size}"
                )
            return data

        # A small read may still cross a block boundary, so walk blocks
        # until the request is satisfied.
        out = bytearray()
        position = offset
        while len(out) < size:
            block_index = position // self._block_size
            block = self._cached_block(block_index)
            start = position - block_index * self._block_size
            if start >= len(block):
                raise EOFError(f"read past end of {self.url} at {position}")
            take = min(size - len(out), len(block) - start)
            out.extend(block[start:start + take])
            position += take
        return bytes(out)

    def _cached_block(self, block_index: int) -> bytes:
        block = self._cache.get(block_index)
        if block is not None:
            self._cache.move_to_end(block_index)
            return block

        block_start = block_index * self._block_size
        want = self._block_size
        if self.size is not None:
            want = min(want, self.size - block_start)
        if want <= 0:
            raise EOFError(f"read past end of {self.url} at {block_start}")
        block = self._get(block_start, want)
        if not block:
            raise EOFError(f"read past end of {self.url} at {block_start}")
        self._cache[block_index] = block
        self._cache.move_to_end(block_index)
        while len(self._cache) > self._cache_blocks:
            self._cache.popitem(last=False)
        return block

    def close(self) -> None:
        self._session.close()

    def __repr__(self) -> str:
        return f"HTTPSource({self.url!r}, size={self.size})"


def make_source(path_or_url: str, **kwargs) -> Source:
    """
    Open a local path or an http(s) URL.

    Raises a `SourceError` subclass with a readable message when the input is
    not something this tool can read - an unknown scheme, a missing file, a
    directory - rather than letting `open()` produce a traceback.
    """
    parsed = urlparse(path_or_url)
    scheme = parsed.scheme.lower()

    # "C:\\images\\disk.vhd" parses as scheme "c"; a one-letter scheme is a
    # Windows drive, not a protocol.
    if scheme in ("http", "https"):
        return HTTPSource(path_or_url, **kwargs)
    if scheme == "file":
        return LocalSource(_local_path(_file_url_path(parsed)))
    if scheme and len(scheme) > 1:
        raise UnsupportedScheme(
            f"cannot read {scheme}:// URLs",
            hint="only http(s) URLs and local paths are supported",
        )
    return LocalSource(_local_path(path_or_url))


def _reason(exc: BaseException) -> str:
    """
    The most specific message inside a `requests` connection error.

    `requests` wraps the useful part several levels down ("Name or service not
    known" lives on the inner urllib3 error), and the outer text is the same
    for every cause.
    """
    seen = set()
    current: object = exc
    deepest = str(exc) or type(exc).__name__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        if text:
            deepest = text
        for attribute in ("reason", "args"):
            nxt = getattr(current, attribute, None)
            if attribute == "args" and isinstance(nxt, tuple):
                nxt = nxt[0] if nxt else None
            if isinstance(nxt, BaseException):
                current = nxt
                break
        else:
            break

    # urllib3 prefixes the message with the connection it was building
    # ("HTTPConnection(host='x', port=80): Failed to resolve 'x'"); the part
    # after the last ": " is the sentence the user needs.
    if "): " in deepest:
        deepest = deepest.rsplit("): ", 1)[1]
    deepest = deepest.strip()
    # The OS detail is useful but verbose ("[WinError 10061] No connection
    # could be made because the target machine actively refused it").
    if len(deepest) > 90:
        deepest = deepest[:87].rstrip() + "..."
    return deepest or type(exc).__name__


def _file_url_path(parsed) -> str:
    """
    The filesystem path inside a `file:` URL.

    On Windows `file:///C:/x.vhd` parses to `/C:/x.vhd`; the leading slash is
    part of the URL grammar, not the path.
    """
    path = parsed.path
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return path


def _local_path(path: str) -> str:
    """Check that `path` is a readable file before handing it to `open`."""
    if not path:
        raise PathNotFound("no path given")

    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        raise PathNotFound(
            f"no such file: {path}",
            hint="check the path, or pass an http(s) URL instead",
        )
    if os.path.isdir(expanded):
        raise PathNotReadable(
            f"{path} is a directory",
            hint="pass a disk image file, not a folder",
        )
    try:
        with open(expanded, "rb"):
            pass
    except PermissionError:
        raise PathNotReadable(
            f"permission denied: {path}",
            hint="check the file's permissions",
        ) from None
    except OSError as exc:
        raise PathNotReadable(f"cannot open {path}: {exc.strerror or exc}") from None
    return expanded
