"""The DEFLATE decoder and the KWZ1 container that compressed uploads arrive in.

zlib is the reference: whatever zlib encodes, at any level, the decoder must
read back exactly. The browser's own encoder is checked against this decoder
too, when a Node that can run TypeScript is available.
"""

from __future__ import annotations

import random
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from kwys.compress import MAGIC, InflateError, TooLarge, inflate, is_packed, unpack

FIXTURES = Path(__file__).parent / "fixtures"
WEB = Path(__file__).parent.parent / "web"


def deflate(data: bytes, level: int = 9) -> bytes:
    c = zlib.compressobj(level, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def kwz(data: bytes, *, size: int | None = None, crc: int | None = None) -> bytes:
    """A container built with zlib, optionally with a lying header."""
    size = len(data) if size is None else size
    crc = zlib.crc32(data) if crc is None else crc
    return struct.pack("<4sIII", MAGIC, size, crc, 0) + deflate(data)


def _samples() -> dict[str, bytes]:
    rng = random.Random(7)
    return {
        "empty": b"",
        "one byte": b"x",
        "long run": b"\0" * 500_000,
        "short period": b"abc" * 10_000,
        "random": rng.randbytes(100_000),
        "text-like": bytes(rng.choice(b"abcdefgh ") for _ in range(100_000)),
        "lease pdf": (FIXTURES / "sample_lease.pdf").read_bytes(),
    }


@pytest.mark.parametrize("level", [0, 1, 6, 9])
@pytest.mark.parametrize("name", list(_samples()))
def test_decodes_whatever_zlib_encodes(name, level):
    data = _samples()[name]
    assert inflate(deflate(data, level), max_size=len(data)) == data


def test_fixed_huffman_blocks():
    # zlib picks fixed codes for short inputs; Z_FIXED forces them throughout.
    data = b"the tenant shall pay the rent " * 200
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_FIXED)
    assert inflate(c.compress(data) + c.flush(), max_size=len(data)) == data


def test_scanned_fixture_round_trips():
    data = (FIXTURES / "sample_lease_scanned.pdf").read_bytes()
    packed = kwz(data)
    assert len(packed) < len(data) / 20
    assert unpack(packed, max_size=len(data)) == data


def test_output_cap_stops_a_decompression_bomb():
    # 10 MB of zeros is ~10 KB compressed. The cap must stop it mid-stream.
    bomb = deflate(b"\0" * 10_000_000)
    assert len(bomb) < 20_000
    with pytest.raises(TooLarge):
        inflate(bomb, max_size=1_000_000)


def test_output_cap_holds_for_literals_too():
    # Huffman-only coding sends every byte as a literal, with no copies to
    # trip the check. One skewed byte value gets a 1-bit code, so the output
    # is about eight times the input: the worst case per input byte.
    data = b"\0" * 400_000 + b"\1"
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9, zlib.Z_HUFFMAN_ONLY)
    stream = c.compress(data) + c.flush()
    assert len(stream) < len(data) / 7
    with pytest.raises(TooLarge):
        inflate(stream, max_size=1000)


def test_header_declaring_too_much_is_refused_before_decoding():
    with pytest.raises(TooLarge):
        unpack(kwz(b"x", size=10**9), max_size=1_000_000)


def test_header_understating_the_size_is_caught_by_the_decoder():
    with pytest.raises(TooLarge):
        unpack(kwz(b"\0" * 100_000, size=10), max_size=1_000_000)


def test_checksum_mismatch_is_refused():
    with pytest.raises(InflateError):
        unpack(kwz(b"hello", crc=0), max_size=100)


@pytest.mark.parametrize("cut", [17, 30, -1])
def test_truncated_upload_is_refused(cut):
    packed = kwz((FIXTURES / "sample_lease.pdf").read_bytes())
    with pytest.raises(InflateError):
        unpack(packed[:cut], max_size=10**6)


def test_garbage_after_the_header_is_refused():
    with pytest.raises(InflateError):
        unpack(MAGIC + bytes(12) + b"\xff" * 64, max_size=10**6)


def test_plain_pdf_is_not_mistaken_for_a_container():
    assert not is_packed((FIXTURES / "sample_lease.pdf").read_bytes())
    assert is_packed(kwz(b"x"))


def _node_runs_typescript() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    probe = subprocess.run(
        [node, "-p", "Boolean(process.features.typescript)"], capture_output=True, text=True
    )
    return probe.stdout.strip() == "true"


@pytest.mark.skipif(not _node_runs_typescript(), reason="needs Node 22.18+ to run the encoder")
@pytest.mark.parametrize("name", ["sample_lease.pdf", "sample_tos.pdf", "sample_lease_scanned.pdf"])
def test_server_decodes_what_the_browser_encodes(name, tmp_path):
    original = (FIXTURES / name).read_bytes()
    out = tmp_path / "packed.kwz"
    subprocess.run(["node", "scripts/pack.ts", str(FIXTURES / name), str(out)], cwd=WEB, check=True)
    assert unpack(out.read_bytes(), max_size=len(original)) == original
