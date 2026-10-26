"""FAT sector cache and cluster-chain walking."""

from __future__ import annotations

from bisect import bisect_left
from collections import OrderedDict
from typing import Dict, Iterator, List, Optional, Tuple

from ...core.volume import ByteView
from .bpb import _u16, _u32

#: Number of FAT sectors kept in the LRU.  64 * 512 B = 32 KiB of FAT.
_FAT_CACHE_SECTORS = 64

#: Clusters between remembered chain positions.  Bounds the cost of seeking
#: deep into a large file without keeping the whole chain in memory.
_CHAIN_CHECKPOINT = 256

def _chain_runs(chain: Iterator[int]) -> Iterator[Tuple[int, int]]:
    """Group a cluster chain into (first cluster, count) runs of neighbours."""
    start = prev = -1
    count = 0
    for cluster in chain:
        if start < 0:
            start = prev = cluster
            count = 1
        elif cluster == prev + 1:
            prev = cluster
            count += 1
        else:
            yield start, count
            start = prev = cluster
            count = 1
    if start >= 0:
        yield start, count

class FatTable:
    """On-demand access to the FAT and to the chains it describes."""

    def __init__(self, view: ByteView, fat_offset: int, bytes_per_sector: int,
                 entry_bits: int, eoc_min: int, bad_cluster: int,
                 max_cluster: int, total_clusters: int):
        self.view = view
        self._fat_offset = fat_offset
        self._bytes_per_sector = bytes_per_sector
        self._entry_bits = entry_bits
        self._eoc_min = eoc_min
        self._bad_cluster = bad_cluster
        self._max_cluster = max_cluster
        self.total_clusters = total_clusters
        self._fat_cache: "OrderedDict[int, bytes]" = OrderedDict()
        self._chain_marks: Dict[int, List[Tuple[int, int]]] = {}
        self._chain_cursor: Dict[int, Tuple[int, int]] = {}

    def _fat_sector(self, sector: int) -> bytes:
        """One sector of the FAT, through the LRU."""
        data = self._fat_cache.get(sector)
        if data is not None:
            self._fat_cache.move_to_end(sector)
            return data
        data = self.view.read(
            self._fat_offset + sector * self._bytes_per_sector,
            self._bytes_per_sector,
        )
        self._fat_cache[sector] = data
        if len(self._fat_cache) > _FAT_CACHE_SECTORS:
            self._fat_cache.popitem(last=False)
        return data

    def _fat_read(self, offset: int, size: int) -> bytes:
        """Read `size` bytes at `offset` within the FAT, sector by sector."""
        bps = self._bytes_per_sector
        out = bytearray(size)
        pos = 0
        while pos < size:
            sector, inner = divmod(offset + pos, bps)
            take = min(size - pos, bps - inner)
            out[pos:pos + take] = self._fat_sector(sector)[inner:inner + take]
            pos += take
        return bytes(out)

    def _fat_entry(self, cluster: int) -> int:
        """The next-cluster value stored for `cluster`."""
        if self._entry_bits == 12:
            raw = self._fat_read(cluster + (cluster >> 1), 2)
            value = raw[0] | (raw[1] << 8)
            return (value >> 4) if cluster & 1 else (value & 0x0FFF)
        if self._entry_bits == 16:
            return _u16(self._fat_read(cluster * 2, 2), 0)
        return _u32(self._fat_read(cluster * 4, 4), 0) & 0x0FFFFFFF

    def _next_cluster(self, cluster: int) -> Optional[int]:
        """The cluster after `cluster`, or None at EOC / on a corrupt value."""
        nxt = self._fat_entry(cluster)
        if (nxt < 2 or nxt >= self._max_cluster
                or nxt >= self._eoc_min or nxt == self._bad_cluster
                or nxt == cluster):
            return None
        return nxt

    def _chain(self, start: int, skip: int = 0) -> Iterator[int]:
        """Yield the clusters of a chain, beginning at position `skip`.

        Positions are checkpointed every `_CHAIN_CHECKPOINT` clusters, so a
        later read further into the same file resumes from the nearest
        checkpoint instead of walking the chain from its head.
        """
        if start < 2 or start >= self._max_cluster:
            return
        marks = self._chain_marks.setdefault(start, [(0, start)])
        pos, current = marks[bisect_left(marks, (skip + 1, -1)) - 1]
        cursor = self._chain_cursor.get(start)
        if cursor is not None and pos < cursor[0] <= skip:
            pos, current = cursor
        while pos < skip:
            nxt = self._next_cluster(current)
            if nxt is None or pos >= self.total_clusters:
                return
            current = nxt
            pos += 1
        if pos:
            self._chain_cursor[start] = (pos, current)
        for _ in range(self.total_clusters + 1 - pos):
            if pos % _CHAIN_CHECKPOINT == 0 and marks[-1][0] < pos:
                marks.append((pos, current))
            yield current
            nxt = self._next_cluster(current)
            if nxt is None:
                return
            current = nxt
            pos += 1

    def _unique_chain(self, start: int) -> Iterator[int]:
        """A chain with repeated clusters dropped, so a corrupt loop ends."""
        seen = set()
        for cluster in self._chain(start):
            if cluster in seen:
                return
            seen.add(cluster)
            yield cluster
