"""
ISO 9660 (ECMA-119) filesystem reader.

On-disk layout
--------------
Volume descriptors occupy 2048-byte logical sectors starting at sector 16.
Each descriptor begins with a type byte, the signature ``CD001`` and a
version.  Type 1 is the Primary Volume Descriptor (PVD); type 2 is a
Supplementary Volume Descriptor, of which Joliet uses the escape sequences
``%/@``, ``%/C`` and ``%/E`` (UCS-2 names).  Type 255 terminates the set.

The PVD's root directory record lives at offset 156 of the descriptor.  It
names the root directory extent as a logical block address; multiplying by
the PVD's logical block size (offset 128) yields the byte offset.

A directory is a sequence of variable-length records.  A zero length byte
ends the current logical block.  No record crosses a block boundary.  A
record is::

    0      length
    1      extended attribute length (in blocks)
    2/6    extent LBA (little/big endian 32-bit)
    10/14  data length (little/big endian 32-bit)
    18     recording date/time (7 bytes)
    25     flags (0x02 directory, 0x80 multi-extent section)
    32     identifier length
    33     identifier

Rock Ridge stores alternate names and metadata in the System Use area after
the identifier and its alignment pad byte.  The SUSP entries used here are
``SP`` (declares SUSP and the number of leading bytes to skip), ``CE``
(continuation area), ``NM`` (name, split across entries with the CONTINUE
flag), ``SK`` (skip), ``CL`` (relocated directory), ``RE`` (relocated entry)
and ``ST`` (terminator).

Only metadata is read during directory traversal; file contents are read on
demand, so a multi-gigabyte ISO is never materialised.
"""

from .reader import IsoReader

__all__ = ["IsoReader"]
