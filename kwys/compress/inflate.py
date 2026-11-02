"""A DEFLATE decoder (RFC 1951), written out rather than delegated to zlib.

DEFLATE is two algorithms stacked. LZ77 replaces a repeated run of bytes with a
back-reference - "copy 258 bytes from 1,405 bytes ago" - and Huffman coding then
gives the commonest literals and references the shortest bit patterns. Decoding
reverses them in one pass: read a Huffman symbol, and it is either a literal
byte, the end of the block, or the length half of a back-reference whose
distance follows.

The one property this module adds over a textbook decoder is a hard output cap.
The input is an upload from a stranger, and a few kilobytes of DEFLATE can
legitimately describe gigabytes of output. Decoding stops the moment the output
passes `max_size`, before the memory is spent, not after.
"""

from __future__ import annotations


class InflateError(ValueError):
    """The stream is malformed, truncated, or decodes past the size cap."""


class TooLarge(InflateError):
    pass


# Lengths 3..258 and distances 1..32768 are each sent as a symbol plus a few
# raw "extra" bits that pick a value within the symbol's range.
_LENGTH_BASE = (
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
    35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258,
)  # fmt: skip
_LENGTH_EXTRA = (
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
)  # fmt: skip
_DIST_BASE = (
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
    257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
    8193, 12289, 16385, 24577,
)  # fmt: skip
_DIST_EXTRA = (
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
    7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13,
)  # fmt: skip

# The order in which a dynamic block lists its code-length code lengths: the
# ones most often unused come last, so they can be left off the end.
_CL_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


class _Huffman:
    """A canonical Huffman code as a single lookup table.

    DEFLATE packs bits least-significant first but writes each Huffman code
    most-significant first, so the table is indexed by the next `bits` input
    bits as they arrive (i.e. bit-reversed codes). Every entry whose low bits
    match a code points at that code's symbol, so one lookup decodes a symbol
    whatever follows it.
    """

    __slots__ = ("bits", "table")

    def __init__(self, lengths: list[int]) -> None:
        bits = max(lengths, default=0)
        if bits == 0:
            # A block that sends no distances at all is legal; any attempt to
            # decode one is then an error, raised by the empty entries below.
            self.bits, self.table = 1, [(-1, 0), (-1, 0)]
            return

        counts = [0] * (bits + 1)
        for n in lengths:
            counts[n] += 1
        counts[0] = 0

        # The Kraft check: more codes of a length than the tree has room for
        # means no prefix code exists, and the stream is corrupt.
        room = 1
        for n in range(1, bits + 1):
            room = (room << 1) - counts[n]
            if room < 0:
                raise InflateError("over-subscribed Huffman code")

        code, next_code = 0, [0] * (bits + 2)
        for n in range(1, bits + 1):
            code = (code + counts[n - 1]) << 1
            next_code[n] = code

        size = 1 << bits
        table: list[tuple[int, int]] = [(-1, 0)] * size
        for symbol, n in enumerate(lengths):
            if not n:
                continue
            code = next_code[n]
            next_code[n] += 1
            rev = int(f"{code:0{n}b}"[::-1], 2)
            for i in range(rev, size, 1 << n):
                table[i] = (symbol, n)
        self.bits, self.table = bits, table


def _fixed_codes() -> tuple[_Huffman, _Huffman]:
    lengths = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
    return _Huffman(lengths), _Huffman([5] * 30)


_FIXED: tuple[_Huffman, _Huffman] | None = None


def inflate(data: bytes, max_size: int) -> bytes:
    """Decode a raw DEFLATE stream, refusing to produce more than `max_size` bytes."""
    global _FIXED

    out = bytearray()
    pos = 0  # next unread input byte
    buf = 0  # bits read but not yet consumed, least significant first
    cnt = 0  # how many bits are in buf
    end = len(data)

    def need(n: int) -> None:
        nonlocal pos, buf, cnt
        while cnt < n:
            if pos >= end:
                raise InflateError("stream ends mid-block")
            buf |= data[pos] << cnt
            pos += 1
            cnt += 8

    def take(n: int) -> int:
        nonlocal buf, cnt
        need(n)
        value = buf & ((1 << n) - 1)
        buf >>= n
        cnt -= n
        return value

    def symbol(code: _Huffman) -> int:
        nonlocal pos, buf, cnt
        # Peek a full table index's worth of bits. Near the end of the stream
        # there may be fewer left than that; zero-padding the peek is safe
        # because the matched code's own length is what gets consumed.
        while cnt < code.bits and pos < end:
            buf |= data[pos] << cnt
            pos += 1
            cnt += 8
        sym, n = code.table[buf & ((1 << code.bits) - 1)]
        if sym < 0 or n > cnt:
            raise InflateError("invalid Huffman code")
        buf >>= n
        cnt -= n
        return sym

    final = 0
    while not final:
        final = take(1)
        kind = take(2)

        if kind == 0:  # stored: byte-aligned raw data, no compression
            buf >>= cnt & 7
            cnt -= cnt & 7
            length, nlength = take(16), take(16)
            if length != nlength ^ 0xFFFF:
                raise InflateError("stored block length check failed")
            # Whole bytes may still sit in the bit buffer; drain those first.
            while cnt and length:
                out.append(take(8))
                length -= 1
            if pos + length > end:
                raise InflateError("stream ends mid-block")
            out += data[pos : pos + length]
            pos += length
            if len(out) > max_size:
                raise TooLarge(f"decoded output exceeds {max_size} bytes")
            continue

        if kind == 1:
            if _FIXED is None:
                _FIXED = _fixed_codes()
            lit, dist = _FIXED
        elif kind == 2:
            lit, dist = _read_dynamic(take, symbol)
        else:
            raise InflateError("reserved block type")

        while True:
            sym = symbol(lit)
            if sym < 256:
                # Checked per literal, not per block: with a 1-bit code a
                # block can expand each input byte into eight output bytes.
                if len(out) >= max_size:
                    raise TooLarge(f"decoded output exceeds {max_size} bytes")
                out.append(sym)
                continue
            if sym == 256:
                break
            sym -= 257
            if sym >= 29:
                raise InflateError("invalid length symbol")
            length = _LENGTH_BASE[sym] + take(_LENGTH_EXTRA[sym])
            d = symbol(dist)
            if d >= 30:
                raise InflateError("invalid distance symbol")
            distance = _DIST_BASE[d] + take(_DIST_EXTRA[d])

            start = len(out) - distance
            if start < 0:
                raise InflateError("back-reference before the start of the output")
            if len(out) + length > max_size:
                raise TooLarge(f"decoded output exceeds {max_size} bytes")
            if distance >= length:
                out += out[start : start + length]
            else:
                # The copy overlaps what it is writing - "repeat the last 1
                # byte 258 times" is how a long run is sent. The source is
                # then a repeating pattern of `distance` bytes.
                pattern = out[start:]
                reps, rest = divmod(length, distance)
                out += pattern * reps + pattern[:rest]
        if len(out) > max_size:
            raise TooLarge(f"decoded output exceeds {max_size} bytes")

    return bytes(out)


def _read_dynamic(take, symbol) -> tuple[_Huffman, _Huffman]:
    """A dynamic block's header: its two Huffman codes, themselves compressed.

    The code lengths for the literal/length and distance alphabets are sent
    as a run-length-encoded sequence, which is in turn Huffman-coded with a
    small third code sent first. Three layers, but each is simple.
    """
    hlit = take(5) + 257
    hdist = take(5) + 1
    hclen = take(4) + 4
    if hlit > 286 or hdist > 30:
        raise InflateError("too many length or distance codes")

    cl_lengths = [0] * 19
    for i in range(hclen):
        cl_lengths[_CL_ORDER[i]] = take(3)
    cl_code = _Huffman(cl_lengths)

    lengths: list[int] = []
    while len(lengths) < hlit + hdist:
        sym = symbol(cl_code)
        if sym < 16:
            lengths.append(sym)
        elif sym == 16:
            if not lengths:
                raise InflateError("repeat with no previous length")
            lengths += [lengths[-1]] * (3 + take(2))
        elif sym == 17:
            lengths += [0] * (3 + take(3))
        else:
            lengths += [0] * (11 + take(7))
    if len(lengths) > hlit + hdist:
        raise InflateError("code lengths overrun the header")
    if lengths[256] == 0:
        raise InflateError("block has no end-of-block code")
    return _Huffman(lengths[:hlit]), _Huffman(lengths[hlit:])
