"""
Errors the user is meant to read.

A disk image is often the wrong file, at the wrong URL, or behind a server
that will not answer. Those are ordinary mistakes, not bugs, so they get a
message and a hint rather than a traceback. Anything raised here is safe to
show verbatim: the text names what failed and what to try next, and never
dumps a stack.

Everything else - an assertion, a struct.error on a malformed image - is a
bug and is left to propagate, because swallowing it would hide the defect.
"""

from __future__ import annotations

from typing import Optional


class VhdPeekError(Exception):
    """Base for errors with a message meant for the user."""

    #: A short, actionable next step. Printed under the message when present.
    hint: Optional[str] = None

    def __init__(self, message: str, hint: Optional[str] = None) -> None:
        super().__init__(message)
        if hint is not None:
            self.hint = hint

    def describe(self) -> str:
        """The message, plus the hint on its own line."""
        if self.hint:
            return f"{self}\n{self.hint}"
        return str(self)


class SourceError(VhdPeekError):
    """The bytes could not be read at all."""


class PathNotFound(SourceError):
    """The local path does not exist."""


class PathNotReadable(SourceError):
    """The local path exists but cannot be opened as a file."""


class UnsupportedScheme(SourceError):
    """The URL uses a scheme this tool does not read."""


class ConnectionFailed(SourceError):
    """The host could not be reached."""


class HttpError(SourceError):
    """The server answered, but not with the image."""

    def __init__(self, message: str, status: int,
                 hint: Optional[str] = None) -> None:
        super().__init__(message, hint)
        self.status = status


class UnknownSize(SourceError):
    """The source will not say how large it is."""


class NotAnImage(VhdPeekError):
    """The bytes were readable, but they are not a VHD or VHDX."""
