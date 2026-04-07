"""Pure-Python CHD v5 reader for CRC32 computation.

Reads compressed disc image hunks without any external tools or libraries.
Supports zlib and lzma codecs — covers all modern PS2/PS1/Dreamcast CHDs.

CHD v5 on-disk layout
----------------------
Header (124 bytes):
  0–7    Tag "MComprHD"
  8–11   Header length (= 124 for v5)
  12–15  Version (= 5)
  16–31  Four codec slots (uint32 big-endian each): 'zlib', 'lzma', etc.
  32–39  Logical bytes (total uncompressed size)
  40–47  Map offset
  48–55  Meta offset
  56–59  Hunk bytes (uncompressed size of each hunk)
  60–63  Unit bytes (logical unit size, e.g. 512 for hard disks)
  64–83  Raw SHA1
  84–103 SHA1
  104–123 Parent SHA1

Map (at map_offset, huffman-compressed):
  0–3   Total compressed map size in bytes (including this 16-byte header)
  4–9   File offset of the first hunk data (6 bytes, big-endian)
  10–11 Map CRC16
  12    length_bits — bits per compressed-length field in each entry
  13    self_bits   — bits per self-reference index field
  14    parent_bits — bits per parent-reference index field
  15    reserved
  16…   Huffman-encoded map entries (one per hunk)

Each decoded map entry carries:
  comp   compression type (0–8)
  length compressed byte count (0 for SELF/PARENT)
  offset file byte offset (hunk index for SELF/PARENT)
  crc16  CRC16 of decompressed hunk

Compression types:
  0–3  compressed with codec slot 0–3
  4    NONE — stored uncompressed
  5    SELF — identical to a previous hunk (offset = that hunk's index)
  6    PARENT — from a parent CHD (not supported here)
  7    RLE_SMALL — repeat previous type 2+ times
  8    RLE_LARGE — repeat previous type 18+ times
"""

import struct
import zlib
import lzma
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_TAG = b"MComprHD"
_V5_HEADER_SIZE = 124
_V5_VERSION = 5

# Codec tags (4 bytes, ASCII)
_CODEC_ZLIB = b"zlib"
_CODEC_LZMA = b"lzma"

# CD-specific codecs — require sector-aware decompression (not yet supported)
_CD_CODECS = {b"cdlz", b"cdzl", b"cdfl"}

# Map compression types
_COMP_CODEC0    = 0
_COMP_CODEC1    = 1
_COMP_CODEC2    = 2
_COMP_CODEC3    = 3
_COMP_NONE      = 4
_COMP_SELF      = 5
_COMP_PARENT    = 6
_COMP_RLE_SMALL = 7
_COMP_RLE_LARGE = 8


class ChdError(Exception):
    """Raised when a CHD file cannot be read or decoded."""


# ---------------------------------------------------------------------------
# Bit-level reader (MSB first)
# ---------------------------------------------------------------------------

class _Bits:
    __slots__ = ("_data", "_pos", "_bit", "__avail")

    def __init__(self, data: bytes, byte_offset: int = 0) -> None:
        self._data = data
        self._pos = byte_offset  # next byte index
        self._bit = 0            # current partial-byte value
        self._avail = 0          # bits left in _bit

    def read(self, n: int) -> int:
        result = 0
        for _ in range(n):
            if self._avail == 0:
                if self._pos >= len(self._data):
                    raise ChdError("Unexpected end of CHD map bitstream")
                self._bit = self._data[self._pos]
                self._pos += 1
                self._avail = 8
            result = (result << 1) | ((self._bit >> (self._avail - 1)) & 1)
            self._avail -= 1
        return result

    # Keep _avail as a proper attribute (not in __slots__ typo fix)
    @property
    def _avail(self):
        return self.__avail

    @_avail.setter
    def _avail(self, v):
        self.__avail = v


# ---------------------------------------------------------------------------
# Canonical Huffman decoder
# ---------------------------------------------------------------------------

class _Huffman:
    """Canonical Huffman decoder — 9 symbols (compression types 0-8).

    The tree is serialised with MAME's import_tree_rle format:
      3 bits: bits_per_length - 1  (so 1–8)
      then for each symbol 0..8:
        if next <bits_per_length> bits != 0 → that is the code length
        else → next 3 bits + 1 = run of zero-length symbols (range 1–8)
    """

    def __init__(self, num_symbols: int) -> None:
        self._nsyms = num_symbols
        self._table: dict[tuple[int, int], int] = {}

    def import_tree_rle(self, bits: _Bits) -> None:
        bpl = bits.read(3) + 1          # bits per length value (range 1–8)
        lengths: list[int] = []
        sym = 0
        while sym < self._nsyms:
            val = bits.read(bpl)
            if val != 0:
                lengths.append(val)
                sym += 1
            else:
                run = bits.read(3) + 1  # zero run (range 1–8)
                lengths.extend([0] * run)
                sym += run

        self._build(lengths[:self._nsyms])

    def _build(self, lengths: list[int]) -> None:
        if not any(lengths):
            return
        max_bits = max(lengths)
        counts = [0] * (max_bits + 1)
        for l in lengths:
            counts[l] += 1
        counts[0] = 0

        # Assign starting canonical codes
        code = 0
        starts = [0] * (max_bits + 2)
        for bits in range(1, max_bits + 1):
            code = (code + counts[bits - 1]) << 1
            starts[bits] = code

        for sym, l in enumerate(lengths):
            if l > 0:
                self._table[(starts[l], l)] = sym
                starts[l] += 1

    def decode_one(self, bits: _Bits) -> int:
        code = 0
        for bit_len in range(1, 17):
            code = (code << 1) | bits.read(1)
            sym = self._table.get((code, bit_len))
            if sym is not None:
                return sym
        raise ChdError("Invalid Huffman code in CHD map")


# ---------------------------------------------------------------------------
# Map decoder
# ---------------------------------------------------------------------------

def _decode_map(map_data: bytes, hunk_count: int, hunk_bytes: int
                ) -> list[tuple[int, int, int, int]]:
    """Decode the CHD v5 compressed map.

    Returns a list of ``(comp_type, length, offset, crc16)`` tuples,
    one per hunk.
    """
    if len(map_data) < 16:
        raise ChdError("CHD map header too short")

    # mapbytes = struct.unpack('>I', map_data[0:4])[0]  # already sliced
    first_offset  = int.from_bytes(map_data[4:10], "big")
    length_bits   = map_data[12]
    self_bits     = map_data[13]
    parent_bits   = map_data[14]

    bits = _Bits(map_data, 16)
    huff = _Huffman(9)
    huff.import_tree_rle(bits)

    entries: list[tuple[int, int, int, int]] = []
    cur_offset = first_offset
    last_comp = 0
    rep_count = 0

    for _ in range(hunk_count):
        if rep_count > 0:
            comp = last_comp
            rep_count -= 1
        else:
            comp = huff.decode_one(bits)
            if comp == _COMP_RLE_SMALL:
                comp = last_comp
                rep_count = 2 + huff.decode_one(bits)
            elif comp == _COMP_RLE_LARGE:
                comp = last_comp
                rep_count = 2 + 16 + (huff.decode_one(bits) << 4) + huff.decode_one(bits)
            else:
                last_comp = comp

        if comp in (_COMP_CODEC0, _COMP_CODEC1, _COMP_CODEC2, _COMP_CODEC3):
            length = bits.read(length_bits)
            offset = cur_offset
            cur_offset += length
            crc16  = bits.read(16)
        elif comp == _COMP_NONE:
            length = hunk_bytes
            offset = cur_offset
            cur_offset += length
            crc16  = bits.read(16)
        elif comp == _COMP_SELF:
            offset = bits.read(self_bits)   # hunk index
            length = 0
            crc16  = 0
        elif comp == _COMP_PARENT:
            offset = bits.read(parent_bits)  # unit index in parent
            length = 0
            crc16  = 0
        else:
            raise ChdError(f"Unknown CHD compression type {comp}")

        entries.append((comp, length, offset, crc16))

    return entries


# ---------------------------------------------------------------------------
# Hunk decompression
# ---------------------------------------------------------------------------

def _decompress(data: bytes, codec: bytes, expected: int) -> bytes:
    """Decompress one CHD hunk."""
    if codec == _CODEC_ZLIB:
        return zlib.decompress(data)

    if codec == _CODEC_LZMA:
        # CHD stores raw LZMA1: 5-byte property header + compressed payload.
        # Property byte encodes lc, lp, pb: byte = lc + (lp + pb*5)*9
        prop = data[0]
        lc = prop % 9
        rem = prop // 9
        lp = rem % 5
        pb = rem // 5
        dict_size = struct.unpack_from("<I", data, 1)[0]
        dec = lzma.LZMADecompressor(
            format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA1,
                      "lc": lc, "lp": lp, "pb": pb,
                      "dict_size": max(dict_size, 1)}],
        )
        return dec.decompress(data[5:], max_length=expected)

    codec_str = codec.decode("ascii", errors="replace")
    raise ChdError(f"Unsupported CHD codec '{codec_str}' — only zlib and lzma are supported")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_chd_sha1(path: Path) -> str:
    """Read the raw-data SHA-1 from a CHD v5 header. No decompression needed.

    Returns a 40-character lowercase hex string, or "" on error.
    """
    try:
        with open(path, "rb") as f:
            hdr = f.read(_V5_HEADER_SIZE)
            if len(hdr) < _V5_HEADER_SIZE or hdr[:8] != _TAG:
                return ""
            version = struct.unpack_from(">I", hdr, 12)[0]
            if version != _V5_VERSION:
                return ""
            # Raw SHA-1 is at offset 64 (20 bytes)
            raw_sha1 = hdr[64:84]
            if raw_sha1 == b"\x00" * 20:
                return ""
            return raw_sha1.hex()
    except OSError:
        return ""


def crc32_of_chd(path: Path) -> str:
    """Return the CRC32 of the raw data stored in a CHD v5 file.

    Streams through all hunks without loading the whole file into memory.
    SELF-referencing hunks are resolved by re-reading the referenced hunk.
    PARENT hunks raise ChdError (parent CHDs are not supported).

    Returns an 8-character lowercase hex string.
    """
    with open(path, "rb") as f:

        # --- Parse header ---
        hdr = f.read(_V5_HEADER_SIZE)
        if len(hdr) < _V5_HEADER_SIZE:
            raise ChdError(f"{path.name}: too short to be a CHD file")
        if hdr[:8] != _TAG:
            raise ChdError(f"{path.name}: not a CHD file (bad tag)")

        version = struct.unpack_from(">I", hdr, 12)[0]
        if version != _V5_VERSION:
            raise ChdError(f"{path.name}: CHD version {version} not supported (need v5)")

        codecs = [hdr[16 + i*4 : 20 + i*4] for i in range(4)]

        # Detect CD-specific codecs early — they require sector-aware decompression
        active_codecs = [c for c in codecs if c != b"\x00\x00\x00\x00"]
        cd_codecs = [c for c in active_codecs if c in _CD_CODECS]
        if cd_codecs:
            names = ", ".join(c.decode("ascii", errors="replace") for c in cd_codecs)
            raise ChdError(
                f"{path.name}: uses CD codec(s) {names} — "
                f"sector-aware decompression not yet supported"
            )

        logical_bytes = struct.unpack_from(">Q", hdr, 32)[0]
        map_offset    = struct.unpack_from(">Q", hdr, 40)[0]
        hunk_bytes    = struct.unpack_from(">I", hdr, 56)[0]

        hunk_count = (logical_bytes + hunk_bytes - 1) // hunk_bytes

        # --- Read and decode map ---
        f.seek(map_offset)
        map_size = struct.unpack(">I", f.read(4))[0]
        f.seek(map_offset)
        raw_map = f.read(map_size)

        entries = _decode_map(raw_map, hunk_count, hunk_bytes)

        # --- Stream hunks, accumulate CRC32 ---
        crc = 0
        remaining = logical_bytes

        def _read_hunk(idx: int) -> bytes:
            """Decompress hunk at index idx (no caching)."""
            hcomp, hlen, hoffset, _ = entries[idx]
            if hcomp in (_COMP_CODEC0, _COMP_CODEC1, _COMP_CODEC2, _COMP_CODEC3):
                f.seek(hoffset)
                return _decompress(f.read(hlen), codecs[hcomp], hunk_bytes)
            if hcomp == _COMP_NONE:
                f.seek(hoffset)
                return f.read(hunk_bytes)
            raise ChdError(f"Cannot resolve hunk {idx} (type {hcomp})")

        for i, (comp, length, offset, _) in enumerate(entries):
            take = min(hunk_bytes, remaining)

            if comp in (_COMP_CODEC0, _COMP_CODEC1, _COMP_CODEC2, _COMP_CODEC3):
                f.seek(offset)
                raw = _decompress(f.read(length), codecs[comp], hunk_bytes)
            elif comp == _COMP_NONE:
                f.seek(offset)
                raw = f.read(hunk_bytes)
            elif comp == _COMP_SELF:
                raw = _read_hunk(int(offset))
            elif comp == _COMP_PARENT:
                raise ChdError(f"{path.name}: PARENT hunks require a parent CHD (not supported)")
            else:
                raise ChdError(f"{path.name}: unknown compression type {comp} in hunk {i}")

            crc = zlib.crc32(raw[:take], crc)
            remaining -= take

    return f"{crc & 0xFFFFFFFF:08x}"
