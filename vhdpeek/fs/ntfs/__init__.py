"""
NTFS filesystem parser.

On-disk layout (all integers little-endian):

  * The boot sector at offset 0 supplies bytes per sector, sectors per
    cluster, the $MFT location and the encoded record sizes.
  * $MFT is an array of FILE records.  Record 0 describes $MFT itself; its
    unnamed $DATA attribute holds the data runs mapping MFT record numbers
    to volume clusters.  Each record begins with an update sequence array
    (USA): the last two bytes of every 512-byte block are replaced by a
    sequence number, and the saved originals in the USA must be restored
    before the record is parsed.
  * A record is a sequence of attributes.  Resident attributes keep their
    value inside the record; non-resident attributes keep a runlist of
    (VCN, LCN, length) extents.  The unnamed $DATA attribute is the file
    content.  $ATTRIBUTE_LIST names fragments stored in extension records.
  * Directories are B-trees keyed by $FILE_NAME.  $INDEX_ROOT (resident)
    holds the root node; $INDEX_ALLOCATION (non-resident) holds INDX records,
    each protected by its own USA.  Both use the same index-entry format.
  * A compressed $DATA attribute stores each compression unit as either
    verbatim clusters or an LZNT1 stream followed by sparse padding.

The parser never reads a whole table: bulk reads are avoided by caching a
bounded number of MFT records and reading only the run extents that a
request touches.
"""

from .reader import NtfsReader

# The class was historically called NTFSReader; keep the public name stable.
NTFSReader = NtfsReader

__all__ = ["NtfsReader", "NTFSReader"]
