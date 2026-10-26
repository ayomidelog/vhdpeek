# Security policy

`vhdpeek` parses untrusted binary formats: disk images, partition tables and
filesystem metadata. A malformed image is the normal input, not an attack in
itself, so parsing must never do anything worse than raise.

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Use GitHub's private reporting: on the repository's **Security** tab, choose
**Report a vulnerability**. That opens a private advisory visible only to the
maintainers.

Please include:

- the affected module or command,
- the smallest image that reproduces it (a few hundred bytes is often enough,
  and a generator snippet from `tests/fixtures/` is ideal),
- what happens versus what should happen,
- the Python version and platform.

You can expect an acknowledgement within a few days. Once a fix is ready, the
advisory is published with credit unless you prefer otherwise.

## Scope

In scope — anything that turns a crafted image into something other than an
exception:

| Class | Example |
|---|---|
| Memory exhaustion | A length field that makes the reader allocate gigabytes |
| Unbounded work | A cluster or run chain that loops forever |
| Path traversal | A filesystem entry whose name escapes the copy-out destination |
| Code execution | `pickle`, `eval` or a shell call reached from image data |
| Credential leak | A URL with an embedded SAS token written to a log or an error |

Out of scope:

- Crashes and tracebacks on malformed images, when nothing worse happens —
  these are ordinary bugs; report them in the issue tracker.
- Reading data the image legitimately contains. `vhdpeek` has no
  authentication of its own: anyone who can fetch the image can read it, so
  protect the image, not the tool.
- Denial of service from an intentionally huge but *well-formed* image.

## Handling remote images

`vhdpeek` only reads, and only the byte ranges it needs. Two things are worth
knowing before pointing it at a URL:

- **Credentials in URLs are not scrubbed.** A SAS token in the URL you pass is
  used for the request and can appear in an exception message or in the
  `Source:` line on stderr. Prefer short-lived tokens, and do not paste live
  URLs into issues.
- **The server sees range requests, not a download.** There is no full fetch,
  so a mistake costs a few kilobytes rather than the whole image.

`RangeNotSupported` is raised rather than falling back to a full download: a
server that ignores `Range` cannot be browsed remotely, and silently
downloading a 60 GiB image is worse than an error.

## Supported versions

Fixes land on `main` and are released from there. Only the latest release is
supported; there are no maintained backport branches.
