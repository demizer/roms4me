"""Pure-Python CHD v5 reader for CRC32 computation.

Reads compressed disc image hunks without any external tools or libraries.
Supports zlib, lzma, and CD codecs (cdlz, cdzl) — covers PS2/PS1/Dreamcast CHDs.

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

CD codec compressed hunk layout (cdlz, cdzl, cdfl):
  [ecc_bitmap: ceil(frames/8) bytes]
  [base_complen: 2 bytes BE (3 if destlen >= 65536)]
  [base compressed data: sector data, using the base codec]
  [subcode compressed data: always raw deflate]
  After decompression, frames with ECC bit set get sync header + ECC restored.

LZMA properties are NOT stored per-hunk. Both compressor and decompressor
compute them from configure_properties(level=8, reduceSize=hunkbytes).
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
_CODEC_CDZL = b"cdzl"
_CODEC_CDLZ = b"cdlz"
_CODEC_CDFL = b"cdfl"

_CD_CODECS = {_CODEC_CDLZ, _CODEC_CDZL, _CODEC_CDFL}

# CD frame constants
_CD_SECTOR_SIZE = 2352
_CD_SUBCODE_SIZE = 96
_CD_FRAME_SIZE = _CD_SECTOR_SIZE + _CD_SUBCODE_SIZE  # 2448

# CD sync header (12 bytes) — restored for ECC-flagged frames
_CD_SYNC_HEADER = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
                         0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])

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
    """Bitstream reader — exact port of MAME's bitstream_in (bitstream.h).

    Uses a 32-bit accumulator buffer with peek/remove semantics.
    Reads zeros past end-of-data (matches MAME behaviour).
    """

    def __init__(self, data: bytes, byte_offset: int = 0) -> None:
        self._data = data
        self._dlength = len(data)
        self._doffset = byte_offset
        self._dbitoffs = 0
        self._buffer = 0
        self._bits = 0

    def peek(self, numbits: int) -> int:
        if numbits == 0:
            return 0
        if numbits > self._bits:
            while self._bits < 32:
                newbits = 0
                if self._doffset < self._dlength:
                    newbits = (self._data[self._doffset] << self._dbitoffs) & 0xFF
                if self._bits + 8 > 32:
                    self._dbitoffs = 32 - self._bits
                    newbits >>= 8 - self._dbitoffs
                    self._buffer |= newbits
                    self._bits += self._dbitoffs
                else:
                    self._buffer |= newbits << (24 - self._bits)
                    self._bits += 8 - self._dbitoffs
                    self._dbitoffs = 0
                    self._doffset += 1
        return (self._buffer >> (32 - numbits)) & ((1 << numbits) - 1)

    def remove(self, numbits: int) -> None:
        self._buffer = (self._buffer << numbits) & 0xFFFFFFFF
        self._bits -= numbits

    def read(self, numbits: int) -> int:
        result = self.peek(numbits)
        self.remove(numbits)
        return result


# ---------------------------------------------------------------------------
# Canonical Huffman decoder
# ---------------------------------------------------------------------------

class _Huffman:
    """Canonical Huffman decoder — 9 symbols (compression types 0-8).

    The tree is serialised with MAME's import_tree_rle format (huffman.cpp):
      numbits = 4 (for maxbits 8–15), 5 (for >=16), 3 (for <8)
      For each symbol:
        read numbits → val
        if val != 1: code length = val
        if val == 1: escape — read another numbits
          if that == 1: code length is literally 1
          else: code length = that value, then read numbits + 3 = repeat count
    """

    def __init__(self, num_symbols: int, max_bits: int = 10) -> None:
        self._nsyms = num_symbols
        self._maxbits = max_bits
        self._table: dict[tuple[int, int], int] = {}
        self._lookup: list[int] = []  # built by _build

    def import_tree_rle(self, bits: _Bits) -> None:
        # Bits per entry depends on max_bits (matches MAME huffman.cpp)
        if self._maxbits >= 16:
            numbits = 5
        elif self._maxbits >= 8:
            numbits = 4
        else:
            numbits = 3

        lengths: list[int] = [0] * self._nsyms
        curnode = 0
        while curnode < self._nsyms:
            nodebits = bits.read(numbits)
            if nodebits != 1:
                # Direct code length
                lengths[curnode] = nodebits
                curnode += 1
            else:
                # Escape: read another value
                nodebits = bits.read(numbits)
                if nodebits == 1:
                    # Double 1 = literal code length of 1
                    lengths[curnode] = 1
                    curnode += 1
                else:
                    # Repeat: this code length for (next value + 3) symbols
                    repcount = bits.read(numbits) + 3
                    while repcount > 0 and curnode < self._nsyms:
                        lengths[curnode] = nodebits
                        curnode += 1
                        repcount -= 1

        self._build(lengths)

    def _build(self, lengths: list[int]) -> None:
        if not any(lengths):
            return

        # MAME's assign_canonical_codes: iterate longest to shortest
        bithisto = [0] * 33
        for l in lengths:
            if 0 < l <= 32:
                bithisto[l] += 1

        curstart = 0
        for codelen in range(32, 0, -1):
            nextstart = (curstart + bithisto[codelen]) >> 1
            bithisto[codelen] = curstart
            curstart = nextstart

        # Assign codes from bithisto starting positions
        for sym, l in enumerate(lengths):
            if l > 0:
                self._table[(bithisto[l], l)] = sym
                bithisto[l] += 1

        # Build MAME-style lookup table (1 << maxbits entries)
        self._lookup = [0] * (1 << self._maxbits)
        for (code, code_len), sym in self._table.items():
            value = (sym << 5) | code_len
            shift = self._maxbits - code_len
            dest = code << shift
            destend = ((code + 1) << shift) - 1
            for entry in range(dest, min(destend + 1, len(self._lookup))):
                self._lookup[entry] = value

    def decode_one(self, bits: _Bits) -> int:
        """Decode one symbol using MAME-style lookup table (peek + remove)."""
        peeked = bits.peek(self._maxbits)
        entry = self._lookup[peeked] if peeked < len(self._lookup) else 0
        numbits = entry & 0x1F
        if numbits == 0:
            raise ChdError("Invalid Huffman code in CHD map")
        bits.remove(numbits)
        return entry >> 5


# ---------------------------------------------------------------------------
# Map decoder
# ---------------------------------------------------------------------------

def _decode_map(map_header: bytes, map_compressed: bytes, hunk_count: int,
                hunk_bytes: int) -> list[tuple[int, int, int, int]]:
    """Decode the CHD v5 compressed map.

    MAME decodes in two passes over one contiguous bitstream:
      Pass 1: Huffman-decode all compression types (with RLE)
      Pass 2: Read length/offset/CRC fields for each entry

    Returns a list of ``(comp_type, length, offset, crc16)`` tuples,
    one per hunk.
    """
    if len(map_header) < 16:
        raise ChdError("CHD map header too short")

    first_offset  = int.from_bytes(map_header[4:10], "big")
    length_bits   = map_header[12]
    self_bits     = map_header[13]
    parent_bits   = map_header[14]

    bits = _Bits(map_compressed, 0)

    # huffman_decoder<16, 8> in MAME — 16 symbols, 8 max bits
    huff = _Huffman(16, 8)
    huff.import_tree_rle(bits)

    # --- Pass 1: decode all compression types ---
    comp_types: list[int] = []
    last_comp = 0
    rep_count = 0
    for _ in range(hunk_count):
        if rep_count > 0:
            comp_types.append(last_comp)
            rep_count -= 1
        else:
            val = huff.decode_one(bits)
            if val == _COMP_RLE_SMALL:
                rep_count = 2 + huff.decode_one(bits)
                comp_types.append(last_comp)
            elif val == _COMP_RLE_LARGE:
                rep_count = 2 + 16 + (huff.decode_one(bits) << 4)
                rep_count += huff.decode_one(bits)
                comp_types.append(last_comp)
            else:
                last_comp = val
                comp_types.append(val)

    # --- Pass 2: read length/offset/CRC fields ---
    # Pseudo-types (9-13) are resolved to base types (5, 6) here.
    _SELF_0   = 9
    _SELF_1   = 10
    _PARENT_SELF = 11
    _PARENT_0 = 12
    _PARENT_1 = 13

    entries: list[tuple[int, int, int, int]] = []
    cur_offset = first_offset
    last_self = 0
    last_parent = 0

    for hunknum, comp in enumerate(comp_types):
        length = 0
        offset = cur_offset
        crc16 = 0

        if comp in (_COMP_CODEC0, _COMP_CODEC1, _COMP_CODEC2, _COMP_CODEC3):
            length = bits.read(length_bits)
            offset = cur_offset
            cur_offset += length
            crc16 = bits.read(16)
        elif comp == _COMP_NONE:
            length = hunk_bytes
            offset = cur_offset
            cur_offset += length
            crc16 = bits.read(16)
        elif comp == _COMP_SELF:
            last_self = offset = bits.read(self_bits)
            comp = _COMP_SELF
        elif comp == _COMP_PARENT:
            offset = bits.read(parent_bits) if parent_bits > 0 else 0
            last_parent = offset
            comp = _COMP_PARENT
        elif comp == _SELF_0:
            offset = last_self
            comp = _COMP_SELF
        elif comp == _SELF_1:
            last_self += 1
            offset = last_self
            comp = _COMP_SELF
        elif comp == _PARENT_SELF:
            last_parent = offset = hunknum  # simplified: hunknum as unit offset
            comp = _COMP_PARENT
        elif comp == _PARENT_0:
            offset = last_parent
            comp = _COMP_PARENT
        elif comp == _PARENT_1:
            last_parent += 1  # simplified: increment by 1 unit
            offset = last_parent
            comp = _COMP_PARENT
        else:
            # Types 14-15 fall through MAME's switch with defaults
            # (no bits read, offset=curoffset, length=0, crc=0)
            pass

        entries.append((comp, length, offset, crc16))

    return entries


# ---------------------------------------------------------------------------
# LZMA property computation (matches MAME's configure_properties)
# ---------------------------------------------------------------------------

def _lzma_props(reduce_size: int) -> dict:
    """Compute LZMA1 filter properties matching MAME's configure_properties.

    MAME uses: level=8, reduceSize=hunkbytes (or sector_bytes for CD).
    LzmaEncProps_Normalize computes dictSize using (2+(i&1))<<(i>>1) series
    (not simple powers of 2), then aligns to the LZMA SDK's dict_size grid.
    """
    # level 8 → initial dictSize = 1 << 26 = 64 MB
    dict_size = 1 << 26

    # Reduce: find smallest value in (2+(i&1))<<(i>>1) series >= reduce_size
    if dict_size > reduce_size:
        for i in range(11, 31):
            candidate = (2 + (i & 1)) << (i >> 1)
            if candidate >= reduce_size:
                dict_size = candidate
                break
        if dict_size > reduce_size:
            dict_size = reduce_size

    # Align to LZMA SDK's dictionary size grid (LzmaEnc_WriteProperties)
    if dict_size >= (1 << 22):
        mask = (1 << 20) - 1
        dict_size = (dict_size + mask) & ~mask
    else:
        for i in range(11, 31):
            if dict_size <= (2 << i):
                dict_size = 2 << i
                break
            if dict_size <= (3 << i):
                dict_size = 3 << i
                break

    return {"id": lzma.FILTER_LZMA1, "lc": 3, "lp": 0, "pb": 2,
            "dict_size": dict_size}


# ---------------------------------------------------------------------------
# Hunk decompression — raw codecs (zlib, lzma)
# ---------------------------------------------------------------------------

def _decompress(data: bytes, codec: bytes, hunk_bytes: int) -> bytes:
    """Decompress one CHD hunk (non-CD codecs)."""
    if codec == _CODEC_ZLIB:
        return zlib.decompress(data, -zlib.MAX_WBITS)

    if codec == _CODEC_LZMA:
        # No props prefix — props are computed from hunk_bytes
        dec = lzma.LZMADecompressor(
            format=lzma.FORMAT_RAW,
            filters=[_lzma_props(hunk_bytes)],
        )
        return dec.decompress(data, max_length=hunk_bytes)

    codec_str = codec.decode("ascii", errors="replace")
    raise ChdError(f"Unsupported CHD codec '{codec_str}'")


# ---------------------------------------------------------------------------
# Hunk decompression — CD codecs (cdzl, cdlz, cdfl)
# ---------------------------------------------------------------------------

def _decompress_cd(data: bytes, codec: bytes, hunk_bytes: int) -> bytes:
    """Decompress a CD-format CHD hunk. Returns only sector data (no subcodes).

    cdlz/cdzl layout: [ecc_bitmap] [base_complen BE] [base data] [subcode data]
    cdfl layout:      [FLAC stream] [zlib subcodes] (no ECC/complen header)
    """
    frames = hunk_bytes // _CD_FRAME_SIZE
    sector_bytes = frames * _CD_SECTOR_SIZE

    if codec == _CODEC_CDFL:
        return _decompress_cd_flac(data, frames, sector_bytes)

    # Parse cdlz/cdzl header
    ecc_bytes = (frames + 7) // 8
    complen_bytes = 2 if hunk_bytes < 65536 else 3
    header_bytes = ecc_bytes + complen_bytes

    if complen_bytes == 3:
        base_complen = (data[ecc_bytes] << 16) | (data[ecc_bytes + 1] << 8) | data[ecc_bytes + 2]
    else:
        base_complen = (data[ecc_bytes] << 8) | data[ecc_bytes + 1]

    base_src = data[header_bytes:header_bytes + base_complen]

    if codec == _CODEC_CDZL:
        sectors = zlib.decompress(base_src, -zlib.MAX_WBITS)
    elif codec == _CODEC_CDLZ:
        dec = lzma.LZMADecompressor(
            format=lzma.FORMAT_RAW,
            filters=[_lzma_props(sector_bytes)],
        )
        sectors = dec.decompress(base_src, max_length=sector_bytes)
    else:
        codec_str = codec.decode("ascii", errors="replace")
        raise ChdError(f"Unknown CD codec '{codec_str}'")

    return sectors[:sector_bytes]


def _decompress_cd_flac(data: bytes, frames: int, sector_bytes: int) -> bytes:
    """Decompress a cdfl hunk using the pure-Python FLAC decoder.

    cdfl hunks have no ECC/complen header — the raw FLAC stream starts at byte 0.
    The FLAC encodes sector data as 16-bit stereo PCM at 44100 Hz.
    After decoding, subcodes are zlib-compressed at the end (skipped — we only
    need sector data).
    """
    from roms4me.analyzers._flac import FlacError, decode_flac_frames

    # Number of stereo sample pairs = sector_bytes / 4 (16-bit × 2 channels)
    num_samples = sector_bytes // 4

    try:
        pcm = decode_flac_frames(data, num_samples, swap_endian=True)
    except FlacError as e:
        raise ChdError(f"FLAC decode failed: {e}") from e

    return pcm[:sector_bytes]


def _extract_cd_sectors(raw: bytes, hunk_bytes: int) -> bytes:
    """Extract only sector data from an uncompressed CD hunk.

    Uncompressed CD hunks are interleaved: [sector(2352) + subcode(96)] × N.
    """
    frames = hunk_bytes // _CD_FRAME_SIZE
    parts = []
    for i in range(frames):
        start = i * _CD_FRAME_SIZE
        parts.append(raw[start : start + _CD_SECTOR_SIZE])
    return b"".join(parts)


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
            raw_sha1 = hdr[64:84]
            if raw_sha1 == b"\x00" * 20:
                return ""
            return raw_sha1.hex()
    except OSError:
        return ""


def crc32_of_chd(path: Path) -> str:
    """Return the CRC32 of the raw data stored in a CHD v5 file.

    Pure Python decompression — no external tools.
    Supports zlib, lzma, and CD codecs (cdlz, cdzl).
    For CD CHDs, extracts MODE1 user data (2048 bytes/sector) to match
    Redump DAT CRCs.

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
        is_cd = any(c in _CD_CODECS for c in codecs)

        logical_bytes = struct.unpack_from(">Q", hdr, 32)[0]
        map_offset    = struct.unpack_from(">Q", hdr, 40)[0]
        hunk_bytes    = struct.unpack_from(">I", hdr, 56)[0]

        hunk_count = (logical_bytes + hunk_bytes - 1) // hunk_bytes

        # --- Read and decode map ---
        # Map header: 16 bytes at map_offset. Then mapbytes of compressed data.
        f.seek(map_offset)
        map_header = f.read(16)
        map_compressed_size = struct.unpack_from(">I", map_header, 0)[0]
        map_compressed = f.read(map_compressed_size)

        entries = _decode_map(map_header, map_compressed, hunk_count, hunk_bytes)

        # --- Stream hunks, accumulate CRC32 ---
        crc = 0
        if is_cd:
            frames_per_hunk = hunk_bytes // _CD_FRAME_SIZE
            sector_per_hunk = frames_per_hunk * _CD_SECTOR_SIZE
            # For CRC: extract user data (first 2048 bytes of each 2352-byte sector).
            # MODE1/SUBTYPE:NONE stores ISO data at offset 0, not the standard MODE1 offset 16.
            _CD_USER_OFFSET = 0
            _CD_USER_SIZE = 2048
            user_per_hunk = frames_per_hunk * _CD_USER_SIZE
            total_frames = logical_bytes // _CD_FRAME_SIZE
            remaining = total_frames * _CD_USER_SIZE
        else:
            sector_per_hunk = hunk_bytes
            user_per_hunk = hunk_bytes
            remaining = logical_bytes

        _decomp = _decompress_cd if is_cd else _decompress

        def _read_hunk(idx: int) -> bytes:
            """Decompress hunk at index idx, extract user data (no caching)."""
            hcomp, hlen, hoffset, _ = entries[idx]
            if hcomp in (_COMP_CODEC0, _COMP_CODEC1, _COMP_CODEC2, _COMP_CODEC3):
                if hlen == 0:
                    return zero_hunk
                f.seek(hoffset)
                return _to_user_data(_decomp(f.read(hlen), codecs[hcomp], hunk_bytes))
            if hcomp == _COMP_NONE:
                f.seek(hoffset)
                raw = f.read(hunk_bytes)
                if is_cd:
                    return _to_user_data(_extract_cd_sectors(raw, hunk_bytes))
                return raw
            if hcomp == _COMP_SELF:
                return _read_hunk(int(hoffset))
            return zero_hunk

        def _to_user_data(sectors: bytes) -> bytes:
            """Extract MODE1 user data (2048 bytes from each 2352-byte sector)."""
            if not is_cd:
                return sectors
            parts = []
            for fr in range(frames_per_hunk):
                start = fr * _CD_SECTOR_SIZE + _CD_USER_OFFSET
                parts.append(sectors[start:start + _CD_USER_SIZE])
            return b"".join(parts)

        # Zero-filled hunk for entries with no data
        zero_hunk = b"\x00" * user_per_hunk

        for i, (comp, length, offset, _) in enumerate(entries):
            take = min(user_per_hunk, remaining)

            if comp in (_COMP_CODEC0, _COMP_CODEC1, _COMP_CODEC2, _COMP_CODEC3):
                if length == 0:
                    raw = zero_hunk
                else:
                    f.seek(offset)
                    raw = _to_user_data(_decomp(f.read(length), codecs[comp], hunk_bytes))
            elif comp == _COMP_NONE:
                f.seek(offset)
                raw_full = f.read(hunk_bytes)
                if is_cd:
                    raw = _to_user_data(_extract_cd_sectors(raw_full, hunk_bytes))
                else:
                    raw = raw_full
            elif comp == _COMP_SELF:
                raw = _read_hunk(int(offset))
            elif comp == _COMP_PARENT:
                raw = zero_hunk
            else:
                raw = zero_hunk

            crc = zlib.crc32(raw[:take], crc)
            remaining -= take

    return f"{crc & 0xFFFFFFFF:08x}"
