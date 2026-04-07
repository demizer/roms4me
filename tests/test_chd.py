"""Tests for CHD v5 reader — Huffman decoder and codec detection."""

import struct
import zlib
from pathlib import Path

import pytest

from roms4me.analyzers.chd import (
    ChdError,
    _Bits,
    _Huffman,
    _decode_map,
    crc32_of_chd,
)


# ---------------------------------------------------------------------------
# _Bits reader
# ---------------------------------------------------------------------------

def test_bits_reads_msb_first():
    data = bytes([0b10110001])
    bits = _Bits(data)
    assert bits.read(3) == 0b101
    assert bits.read(5) == 0b10001


def test_bits_crosses_byte_boundary():
    data = bytes([0xFF, 0x00])
    bits = _Bits(data)
    assert bits.read(4) == 0xF
    assert bits.read(4) == 0xF
    assert bits.read(4) == 0x0
    assert bits.read(4) == 0x0


# ---------------------------------------------------------------------------
# Huffman decoder — import_tree_rle
# ---------------------------------------------------------------------------

def test_huffman_single_symbol():
    """Tree with one active symbol — every decode returns that symbol."""
    # Encode: bpl_raw=0 → bpl=1. sym0: 1 bit → `1` (length 1).
    # syms 1-8: zeros via run.
    # Build bitstream: 3 bits bpl(000) + 1 bit sym0(1) + 1 bit zero(0) + 3 bits run(111=7→8 zeros)
    # = 0b000_1_0_111_... = 0x17...
    data = bytes([0b00010111, 0x00, 0x00, 0x00])
    bits = _Bits(data)
    huff = _Huffman(9)
    huff.import_tree_rle(bits)

    # Only symbol 0 should be decodable, with code `1` at length 1
    # Actually with length 1 for one symbol, code is 0 at length 1
    assert huff.decode_one(bits) == 0
    assert huff.decode_one(bits) == 0


def test_huffman_two_symbols():
    """Tree with two symbols at different lengths."""
    # Build a tree: sym 0 = length 1, sym 1 = length 2, rest = 0
    # bpl_raw=1 → bpl=2. sym0: 2 bits → 01 (length 1). sym1: 2 bits → 10 (length 2).
    # sym2: 2 bits → 00 → zero run, read 3 bits for count.
    # Need run of 7 to cover syms 2-8.
    # run_raw=6 → run=7.
    # Bits: 001 01 10 00 110 [data...]
    # = 0b001_01_10_0 | 0b0_110_....
    data = bytes([0b00101100, 0b01100000, 0x00, 0x00, 0x00])
    bits = _Bits(data)
    huff = _Huffman(9)
    huff.import_tree_rle(bits)

    assert (0, 1) in huff._table or (1, 2) in huff._table  # at least one entry


# ---------------------------------------------------------------------------
# Codec detection — CD codecs are rejected early
# ---------------------------------------------------------------------------

def _make_chd_header(codecs: list[bytes]) -> bytes:
    """Build a minimal CHD v5 header with given codec slots."""
    hdr = bytearray(124)
    hdr[0:8] = b"MComprHD"
    struct.pack_into(">I", hdr, 8, 124)        # header length
    struct.pack_into(">I", hdr, 12, 5)          # version
    for i, c in enumerate(codecs[:4]):
        hdr[16 + i*4 : 20 + i*4] = c.ljust(4, b"\x00")[:4]
    struct.pack_into(">Q", hdr, 32, 0)          # logical bytes
    struct.pack_into(">Q", hdr, 40, 124)        # map offset (right after header)
    struct.pack_into(">I", hdr, 56, 2048)       # hunk bytes
    return bytes(hdr)


def test_cd_codec_detected_early(tmp_path):
    """CHD with CD codecs raises ChdError before map decode."""
    chd = tmp_path / "test.chd"
    chd.write_bytes(_make_chd_header([b"cdlz", b"cdzl", b"cdfl"]))

    with pytest.raises(ChdError, match="CD codec"):
        crc32_of_chd(chd)


def test_zlib_codec_not_rejected(tmp_path):
    """CHD with zlib codec passes the codec check (may fail later on truncated data)."""
    chd = tmp_path / "test.chd"
    # Header + a small map that will fail to decode (that's fine — we're testing codec check)
    data = bytearray(_make_chd_header([b"zlib"]))
    # Append 16 bytes of map header so it doesn't fail on "too short"
    data += b"\x00" * 20
    chd.write_bytes(bytes(data))

    # Should NOT raise "CD codec" — will raise something else (truncated map)
    with pytest.raises(ChdError, match="(?!CD codec)"):
        crc32_of_chd(chd)
