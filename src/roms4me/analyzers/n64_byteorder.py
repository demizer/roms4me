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
    "bigendian":    "Big Endian (.z64)",
    "byteswapped":  "Byte Swapped (.v64) — every byte pair swapped",
    "littleendian": "Little Endian (.n64) — every 4-byte group reversed",
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

    def analyze_file(self, rom_path: Path, dat: DatFile, crc: str = "") -> list[Suggestion]:
        """Read ROM, try all N64 byte-order conversions, lookup normalized CRC in DAT.

        Tries both ByteSwapped→BigEndian and LittleEndian→BigEndian conversions
        regardless of the detected format.  This handles ROMs whose magic bytes
        disagree with their file extension (e.g. a .v64 that magic-detects as
        BigEndian) by exhaustively checking all interpretations.
        """
        from roms4me.handlers.registry import get_rom_extensions
        # Include all N64 format variants so zips with .v64/.n64 are found
        accepted = set(get_rom_extensions(dat.name)) or None
        rom_data = _read_rom_data(rom_path, accepted)
        if not rom_data:
            return []

        fmt = detect_n64_format(rom_data)
        if fmt is None:
            return []  # Not an N64 ROM — magic bytes don't match any N64 format

        # Build CRC → game lookup once
        crc_to_game: dict[str, list] = {}
        for game in dat.games:
            for rom in game.roms:
                if rom.crc:
                    crc_to_game.setdefault(rom.crc.lower(), []).append(game)

        original_crc = f"{zlib.crc32(rom_data) & 0xFFFFFFFF:08x}"
        label = _FORMAT_LABEL.get(fmt, fmt)
        suggestions: list[Suggestion] = []
        tried_crcs: set[str] = {original_crc}  # skip raw CRC — CrcLookupAnalyzer handles it

        # Try every non-BigEndian interpretation and normalize to BigEndian.
        # "byteswapped" swaps byte pairs; "littleendian" reverses 4-byte groups.
        # This catches ROMs whose detected format disagrees with their content
        # (e.g. wrong extension, non-standard magic bytes, partially converted dumps).
        for try_fmt in ("byteswapped", "littleendian"):
            normalized = to_bigendian(rom_data, try_fmt)
            norm_crc = f"{zlib.crc32(normalized) & 0xFFFFFFFF:08x}"

            if norm_crc in tried_crcs:
                continue
            tried_crcs.add(norm_crc)

            if norm_crc not in crc_to_game:
                continue

            for game in crc_to_game[norm_crc]:
                suggestions.append(Suggestion(
                    dat_game_name=game.name,
                    confidence=1.0,
                    reason=(
                        f"ROM detected as {label}. "
                        f"CRC verified after treating as {_FORMAT_LABEL.get(try_fmt, try_fmt)} "
                        f"and normalizing to Big Endian: {norm_crc} (raw: {original_crc}). "
                        f"All three N64 formats (.z64/.v64/.n64) hold identical data in different "
                        f"byte orders; Big Endian (.z64) is the No-Intro standard."
                    ),
                    expected_crc=norm_crc,
                    actual_crc=original_crc,
                    crc_match=True,
                    action="rename",
                ))

        return suggestions

    def diagnose(self, rom_path: Path, dat: DatFile) -> list[str]:
        """Return diagnostic strings about N64 format detection and CRC conversion attempts.

        Called by the pipeline when no confirmed match was found. Re-runs format
        detection and all byte-order conversions, reporting each CRC and whether
        it appears in the DAT.
        """
        from roms4me.handlers.registry import get_rom_extensions
        accepted = set(get_rom_extensions(dat.name)) or None
        rom_data = _read_rom_data(rom_path, accepted)
        if not rom_data:
            return []

        fmt = detect_n64_format(rom_data)
        if fmt is None:
            return []

        label = _FORMAT_LABEL.get(fmt, fmt)
        dat_crcs: set[str] = {r.crc.lower() for g in dat.games for r in g.roms if r.crc}
        raw_crc = f"{zlib.crc32(rom_data) & 0xFFFFFFFF:08x}"

        msgs = [
            f"N64 format detected: {label}",
            f"Raw CRC: {raw_crc} ({'in DAT' if raw_crc in dat_crcs else 'not in DAT'})",
        ]
        for try_fmt in ("byteswapped", "littleendian"):
            norm = to_bigendian(rom_data, try_fmt)
            norm_crc = f"{zlib.crc32(norm) & 0xFFFFFFFF:08x}"
            if norm_crc == raw_crc:
                continue
            in_dat = norm_crc in dat_crcs
            msgs.append(
                f"Tried as {_FORMAT_LABEL.get(try_fmt, try_fmt)}: "
                f"{norm_crc} → {'MATCH' if in_dat else 'no match'}"
            )
        return msgs
