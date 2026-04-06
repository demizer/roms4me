"""Tests for N64 byte-order normalization analyzer.

Covers:
- detect_n64_format: BigEndian, ByteSwapped, LittleEndian, unknown
- to_bigendian: correct byte-order conversion for each format
- N64ByteOrderAnalyzer: finds CRC match for non-BigEndian ROMs (loose and zipped)
- pipeline.analyze_rom: end-to-end match for ByteSwapped and LittleEndian ROMs
"""

import zipfile
import zlib
from pathlib import Path

from roms4me.analyzers.n64_byteorder import N64ByteOrderAnalyzer, detect_n64_format, to_bigendian
from roms4me.analyzers.pipeline import analyze_rom


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 128-byte fake BigEndian N64 ROM (starts with magic 80 37 12 40)
_BE_ROM = bytes([0x80, 0x37, 0x12, 0x40]) + b"\xAA\xBB\xCC\xDD" * 31


def _byteswap(data: bytes) -> bytes:
    """Swap every pair of bytes (BigEndian ↔ ByteSwapped)."""
    arr = bytearray(data)
    for i in range(0, len(arr) - 1, 2):
        arr[i], arr[i + 1] = arr[i + 1], arr[i]
    return bytes(arr)


def _le_swap(data: bytes) -> bytes:
    """Reverse each group of 4 bytes (BigEndian ↔ LittleEndian)."""
    arr = bytearray(data)
    for i in range(0, len(arr) - 3, 4):
        arr[i], arr[i + 1], arr[i + 2], arr[i + 3] = (
            arr[i + 3], arr[i + 2], arr[i + 1], arr[i]
        )
    return bytes(arr)


_V64_ROM = _byteswap(_BE_ROM)  # ByteSwapped version (magic: 37 80)
_N64_ROM = _le_swap(_BE_ROM)   # LittleEndian version (magic: 40 12)


def _make_dat(game_name: str, rom_name: str, be_data: bytes):
    """Build a minimal DatFile with the BigEndian CRC for be_data."""
    from roms4me.models.dat import DatFile, GameEntry, RomEntry

    crc = f"{zlib.crc32(be_data) & 0xFFFFFFFF:08x}"
    rom = RomEntry(name=rom_name, size=len(be_data), crc=crc)
    game = GameEntry(name=game_name, description=game_name, roms=[rom])
    return DatFile(name="Nintendo - Nintendo 64 (BigEndian)", file_path="", games=[game])


def _write_zip(path: Path, inner_name: str, data: bytes) -> Path:
    """Write a zip containing one file."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(inner_name, data)
    return path


# ---------------------------------------------------------------------------
# detect_n64_format
# ---------------------------------------------------------------------------


def test_detect_bigendian():
    assert detect_n64_format(_BE_ROM) == "bigendian"


def test_detect_byteswapped():
    assert detect_n64_format(_V64_ROM) == "byteswapped"


def test_detect_littleendian():
    assert detect_n64_format(_N64_ROM) == "littleendian"


def test_detect_unknown_returns_none():
    assert detect_n64_format(b"\x00\x00\x00\x00") is None


def test_detect_short_data_returns_none():
    assert detect_n64_format(b"\x80") is None


# ---------------------------------------------------------------------------
# to_bigendian
# ---------------------------------------------------------------------------


def test_byteswapped_roundtrip():
    """Converting ByteSwapped ROM to BigEndian gives back the original."""
    assert to_bigendian(_V64_ROM, "byteswapped") == _BE_ROM


def test_littleendian_roundtrip():
    """Converting LittleEndian ROM to BigEndian gives back the original."""
    assert to_bigendian(_N64_ROM, "littleendian") == _BE_ROM


def test_bigendian_noop():
    """BigEndian conversion is a no-op."""
    assert to_bigendian(_BE_ROM, "bigendian") == _BE_ROM


# ---------------------------------------------------------------------------
# N64ByteOrderAnalyzer — loose files
# ---------------------------------------------------------------------------


def test_analyzer_matches_byteswapped_loose(tmp_path):
    """ByteSwapped .v64 file — analyzer finds BigEndian CRC match in DAT."""
    src = tmp_path / "WWF No Mercy (USA) (Rev 1).v64"
    src.write_bytes(_V64_ROM)
    dat = _make_dat("WWF No Mercy (USA) (Rev 1)", "WWF No Mercy (USA) (Rev 1).z64", _BE_ROM)

    analyzer = N64ByteOrderAnalyzer()
    suggestions = analyzer.analyze_file(src, dat)

    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.dat_game_name == "WWF No Mercy (USA) (Rev 1)"
    assert s.crc_match is True
    assert "ByteSwapped" in s.reason


def test_analyzer_matches_littleendian_loose(tmp_path):
    """LittleEndian .n64 file — analyzer finds BigEndian CRC match in DAT."""
    src = tmp_path / "Game (USA).n64"
    src.write_bytes(_N64_ROM)
    dat = _make_dat("Game (USA)", "Game (USA).z64", _BE_ROM)

    analyzer = N64ByteOrderAnalyzer()
    suggestions = analyzer.analyze_file(src, dat)

    assert len(suggestions) == 1
    assert suggestions[0].crc_match is True
    assert "LittleEndian" in suggestions[0].reason


def test_analyzer_skips_bigendian(tmp_path):
    """BigEndian ROM is already handled by CrcLookupAnalyzer — N64 analyzer returns empty."""
    src = tmp_path / "Game (USA).z64"
    src.write_bytes(_BE_ROM)
    dat = _make_dat("Game (USA)", "Game (USA).z64", _BE_ROM)

    analyzer = N64ByteOrderAnalyzer()
    assert analyzer.analyze_file(src, dat) == []


def test_analyzer_skips_non_n64(tmp_path):
    """Non-N64 data (e.g. SNES ROM) — analyzer returns empty."""
    src = tmp_path / "Game (USA).sfc"
    src.write_bytes(b"\x00" * 128)
    dat = _make_dat("Game (USA)", "Game (USA).sfc", b"\x00" * 128)

    analyzer = N64ByteOrderAnalyzer()
    assert analyzer.analyze_file(src, dat) == []


# ---------------------------------------------------------------------------
# N64ByteOrderAnalyzer — zipped ROMs
# ---------------------------------------------------------------------------


def test_analyzer_matches_byteswapped_zipped(tmp_path):
    """ByteSwapped ROM inside a zip — analyzer reads, normalizes, and finds match."""
    src = _write_zip(
        tmp_path / "WWF No Mercy (USA) (Rev 1).zip",
        "WWF No Mercy (USA) (Rev 1).v64",
        _V64_ROM,
    )
    dat = _make_dat("WWF No Mercy (USA) (Rev 1)", "WWF No Mercy (USA) (Rev 1).z64", _BE_ROM)

    analyzer = N64ByteOrderAnalyzer()
    suggestions = analyzer.analyze_file(src, dat)

    assert len(suggestions) == 1
    assert suggestions[0].crc_match is True


# ---------------------------------------------------------------------------
# analyze_rom pipeline — end-to-end
# ---------------------------------------------------------------------------


def test_pipeline_matches_byteswapped_via_name_then_crc(tmp_path):
    """Full pipeline: ByteSwapped ROM named identically to DAT entry — confirms via byte-order CRC."""
    src = _write_zip(
        tmp_path / "WWF No Mercy (USA) (Rev 1).zip",
        "WWF No Mercy (USA) (Rev 1).v64",
        _V64_ROM,
    )
    dat = _make_dat("WWF No Mercy (USA) (Rev 1)", "WWF No Mercy (USA) (Rev 1).z64", _BE_ROM)

    result = analyze_rom(src, dat, verify_crc=True)

    assert result.suggestions, "Pipeline should produce at least one suggestion"
    best = result.suggestions[0]
    assert best.crc_match is True
    assert best.dat_game_name == "WWF No Mercy (USA) (Rev 1)"


def test_pipeline_matches_byteswapped_no_name_hint(tmp_path):
    """Byte-order match via file-based analyzer even when filename gives no name hint."""
    # Use a generic filename that won't hint the game name
    src = _write_zip(
        tmp_path / "unknown_dump_12345.zip",
        "unknown_dump_12345.v64",
        _V64_ROM,
    )
    dat = _make_dat("WWF No Mercy (USA) (Rev 1)", "WWF No Mercy (USA) (Rev 1).z64", _BE_ROM)

    result = analyze_rom(src, dat, verify_crc=True)

    crc_matches = [s for s in result.suggestions if s.crc_match is True]
    assert crc_matches, "Should find a CRC match via byte-order normalization even with no name hint"
    assert crc_matches[0].dat_game_name == "WWF No Mercy (USA) (Rev 1)"
