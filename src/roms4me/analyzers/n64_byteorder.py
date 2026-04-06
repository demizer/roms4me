"""N64 byte-order analyzer — normalizes ByteSwapped and LittleEndian ROMs to BigEndian.

No-Intro N64 DATs use BigEndian (.z64) CRCs.  ROMs distributed online often
arrive as ByteSwapped (.v64) or LittleEndian (.n64).  The CRC of a swapped
ROM is completely different from the BigEndian CRC, so direct lookup fails.

Format detection uses the first two magic bytes:
  BigEndian  (.z64): 80 37
  ByteSwapped (.v64): 37 80
  LittleEndian (.n64): 40 12

Conversions to BigEndian:
  ByteSwapped  → swap every pair of bytes:   [A,B,C,D] → [B,A,D,C]
  LittleEndian → reverse every group of four: [A,B,C,D] → [D,C,B,A]
"""

import logging
import zipfile
import zlib
from pathlib import Path

from roms4me.analyzers.base import Suggestion
from roms4me.models.dat import DatFile

log = logging.getLogger(__name__)

# Magic-byte prefix → format name
_MAGIC: dict[bytes, str] = {
    b"\x80\x37": "bigendian",
    b"\x37\x80": "byteswapped",
    b"\x40\x12": "littleendian",
}

_FORMAT_LABEL: dict[str, str] = {
    "byteswapped": "ByteSwapped (.v64)",
    "littleendian": "LittleEndian (.n64)",
}


def detect_n64_format(data: bytes) -> str | None:
    """Return 'bigendian', 'byteswapped', 'littleendian', or None if not an N64 ROM."""
    if len(data) < 4:
        return None
    return _MAGIC.get(bytes(data[:2]))


def to_bigendian(data: bytes, fmt: str) -> bytes:
    """Return data converted to BigEndian layout.  'bigendian' is a no-op."""
    if fmt == "bigendian":
        return data
    arr = bytearray(data)
    if fmt == "byteswapped":
        for i in range(0, len(arr) - 1, 2):
            arr[i], arr[i + 1] = arr[i + 1], arr[i]
    elif fmt == "littleendian":
        for i in range(0, len(arr) - 3, 4):
            arr[i], arr[i + 1], arr[i + 2], arr[i + 3] = (
                arr[i + 3], arr[i + 2], arr[i + 1], arr[i]
            )
    return bytes(arr)


def _read_rom_data(rom_path: Path, accepted_exts: set[str] | None = None) -> bytes | None:
    """Read the primary ROM data from a file or zip.

    accepted_exts: whitelist of lowercase extensions (e.g. {'.z64', '.v64', '.n64'}).
    Falls back to the largest file in the archive when nothing matches.
    """
    try:
        if rom_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(rom_path, "r") as zf:
                entries = [e for e in zf.infolist() if not e.is_dir()]
                if accepted_exts:
                    candidates = [e for e in entries if Path(e.filename).suffix.lower() in accepted_exts]
                    if not candidates:
                        candidates = entries
                else:
                    candidates = entries
                if candidates:
                    best = max(candidates, key=lambda e: e.file_size)
                    return zf.read(best.filename)
        else:
            return rom_path.read_bytes()
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("N64ByteOrderAnalyzer: could not read %s: %s", rom_path, e)
    return None


class N64ByteOrderAnalyzer:
    """File-based analyzer: detects non-BigEndian N64 ROMs and matches via normalized CRC."""

    name = "n64_byteorder"

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """Name-only analysis not applicable — file access required."""
        return []

    def analyze_file(self, rom_path: Path, dat: DatFile) -> list[Suggestion]:
        """Read ROM, detect byte order, normalize to BigEndian, lookup CRC in DAT."""
        from roms4me.handlers.registry import get_rom_extensions
        # Include all N64 format variants so zips with .v64/.n64 are found
        accepted = set(get_rom_extensions(dat.name)) or None
        rom_data = _read_rom_data(rom_path, accepted)
        if not rom_data:
            return []

        fmt = detect_n64_format(rom_data)
        if fmt is None or fmt == "bigendian":
            # Not N64, or already BigEndian — CrcLookupAnalyzer handles this
            return []

        normalized = to_bigendian(rom_data, fmt)
        normalized_crc = f"{zlib.crc32(normalized) & 0xFFFFFFFF:08x}"

        # Build CRC → game lookup
        crc_to_game: dict[str, list] = {}
        for game in dat.games:
            for rom in game.roms:
                if rom.crc:
                    crc_to_game.setdefault(rom.crc.lower(), []).append(game)

        if normalized_crc not in crc_to_game:
            return []

        label = _FORMAT_LABEL.get(fmt, fmt)
        original_crc = f"{zlib.crc32(rom_data) & 0xFFFFFFFF:08x}"

        suggestions = []
        for game in crc_to_game[normalized_crc]:
            suggestions.append(Suggestion(
                dat_game_name=game.name,
                confidence=1.0,
                reason=(
                    f"ROM is {label}; BigEndian CRC after conversion matches DAT. "
                    f"Convert to .z64 format for a clean export."
                ),
                expected_crc=normalized_crc,
                actual_crc=original_crc,
                crc_match=True,
                action="rename",
            ))
        return suggestions
