"""LZNT1 decompression and compressed-stream reads."""

from __future__ import annotations

from typing import List, Optional

from .attributes import _read_runs
from .records import _Attr, _u16


def _read_compressed(
    reader, attr: _Attr, offset: int, size: Optional[int]
) -> bytes:
    """Read a compressed non-resident stream one compression unit at a time."""
    if offset < 0:
        offset = 0
    total = attr.data_size
    if size is None:
        size = total - offset
    if size <= 0 or offset >= total:
        return b""
    if size > total - offset:
        size = total - offset
    initialized = attr.initialized_size or total
    if attr.compression_unit > 16:
        return _read_runs(reader, attr.runs, total, offset, size, initialized)
    unit_clusters = 1 << attr.compression_unit
    unit_size = unit_clusters * reader.cluster_size
    if unit_size <= 0 or unit_size > (1 << 26):
        return _read_runs(reader, attr.runs, total, offset, size, initialized)

    out = bytearray(size)
    first_unit = offset // unit_size
    last_unit = (offset + size - 1) // unit_size
    for unit_index in range(first_unit, last_unit + 1):
        unit = _read_compression_unit(
            reader, attr, unit_index, unit_clusters, unit_size
        )
        unit_start = unit_index * unit_size
        low = max(offset, unit_start)
        high = min(offset + size, unit_start + unit_size, initialized)
        if high > low:
            out[low - offset:high - offset] = unit[
                low - unit_start:high - unit_start
            ]
    return bytes(out)


def _read_compression_unit(
    reader, attr: _Attr, unit_index: int, unit_clusters: int, unit_size: int
) -> bytes:
    start_vcn = unit_index * unit_clusters
    end_vcn = start_vcn + unit_clusters
    addresses: List[Optional[int]] = [None] * unit_clusters
    for run in attr.runs:
        run_end = run.vcn + run.count
        low = max(start_vcn, run.vcn)
        high = min(end_vcn, run_end)
        if high <= low:
            continue
        base = None if run.lcn is None else run.lcn + (low - run.vcn)
        for vcn in range(low, high):
            addresses[vcn - start_vcn] = (
                None if base is None else base + (vcn - low)
            )

    if all(address is None for address in addresses):
        return b"\x00" * unit_size

    # A zero at the end of the unit means the unit was compressed; the
    # leading physical clusters hold the LZNT1 stream and the rest is
    # sparse padding.  Otherwise the whole unit is stored verbatim.
    if addresses[-1] is None:
        compressed = bytearray()
        for address in addresses:
            if address is None:
                break
            compressed += reader.view.read(
                address * reader.cluster_size, reader.cluster_size
            )
        return _lznt1_decompress(bytes(compressed), unit_size)

    raw = bytearray()
    for address in addresses:
        if address is None:
            raw += b"\x00" * reader.cluster_size
        else:
            raw += reader.view.read(
                address * reader.cluster_size, reader.cluster_size
            )
    return bytes(raw[:unit_size])


def _lznt1_decompress(data: bytes, expected_size: int) -> bytes:
    out = bytearray()
    pos = 0
    while pos + 2 <= len(data) and len(out) < expected_size:
        header = _u16(data, pos)
        if header == 0:
            break
        block_size = (header & 0x0FFF) + 3
        if block_size <= 3:
            break
        block_end = min(pos + block_size, len(data))
        compressed = bool(header & 0x8000)
        pos += 2

        if not compressed:
            out += data[pos:min(block_end, pos + 4096)]
            pos = block_end
            continue

        block = bytearray()
        while pos < block_end and len(block) < 4096:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= block_end or len(block) >= 4096:
                    break
                if not (flags >> bit) & 1:
                    block.append(data[pos])
                    pos += 1
                else:
                    if pos + 2 > block_end:
                        break
                    phrase = _u16(data, pos)
                    pos += 2
                    length = (phrase >> 12) + 3
                    displacement = (phrase & 0x0FFF) + 1
                    source = len(block) - displacement
                    if source < 0:
                        return b"\x00" * expected_size
                    for _ in range(length):
                        if len(block) >= 4096:
                            break
                        block.append(block[source])
                        source += 1
        out += block
        pos = block_end

    if len(out) < expected_size:
        out += b"\x00" * (expected_size - len(out))
    return bytes(out[:expected_size])
