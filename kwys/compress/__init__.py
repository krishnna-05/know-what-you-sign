"""Uploads compressed in the browser, unpacked here.

A scanned agreement is often stored as raw page images: the 3-page fixture is
16.7 MB, almost all of it white pixels. The reader is typically on mobile data,
so the browser compresses the PDF before sending it and this package restores
it. The file is never kept in either form; this only shortens the upload.

The wire format ("KWZ1") is a 16-byte header around a raw DEFLATE stream:

    offset  size  field
    0       4     magic, b"KWZ1"
    4       4     original size, little-endian
    8       4     CRC-32 of the original bytes, little-endian
    12      4     reserved, zero
    16      ...   raw DEFLATE (RFC 1951)

A plain PDF never starts with the magic, so either may be uploaded to the same
endpoint and the CLI and API clients that send plain PDFs keep working.
"""

from __future__ import annotations

import struct
import zlib

from kwys.compress.inflate import InflateError, TooLarge, inflate

MAGIC = b"KWZ1"
_HEADER = struct.Struct("<4sIII")

__all__ = ["MAGIC", "InflateError", "TooLarge", "inflate", "is_packed", "unpack"]


def is_packed(payload: bytes) -> bool:
    return payload.startswith(MAGIC)


def unpack(payload: bytes, max_size: int) -> bytes:
    """The original file from a KWZ1 upload, or InflateError if it is not intact.

    The declared size is checked before decoding starts, so an honest oversized
    upload is refused at once, and the decoder enforces the same cap as it
    goes, so a dishonest header cannot get past it either.
    """
    if len(payload) < _HEADER.size:
        raise InflateError("compressed upload is shorter than its header")
    magic, size, crc, _reserved = _HEADER.unpack_from(payload)
    if magic != MAGIC:
        raise InflateError("not a compressed upload")
    if size > max_size:
        raise TooLarge(f"decoded output exceeds {max_size} bytes")

    out = inflate(payload[_HEADER.size :], max_size=size)
    if len(out) != size or zlib.crc32(out) != crc:
        raise InflateError("compressed upload does not match its checksum")
    return out
