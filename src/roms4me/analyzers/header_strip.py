"""Header strip analyzer — detects and strips copier headers to find CRC matches.

Many older ROM dumps include copier headers (SMC, SWC, FIG for SNES, iNES for NES, etc.)
that aren't part of the actual ROM data. DAT files typically reference the headerless CRC.

This analyzer:
1. Detects known header signatures by checking file size (DAT size + header size)
2. Strips common header sizes (512 bytes for SNES, 16 bytes for NES)
3. Recomputes CRC on the stripped data and checks against DAT entries
"""

import logging
import zipfile
import zlib
from pathlib import Path

from roms4me.analyzers.base import Suggestion
from roms4me.models.dat import DatFile

log = logging.getLogger(__name__)

# Known header sizes to try stripping, with descriptions
HEADER_SIZES = [
    (512, "SMC/SWC copier header (SNES)"),
    (16, "iNES header (NES)"),
    (64, "Lynx header"),
    (8192, "Atari 7800 header"),
]


class HeaderStripAnalyzer:
    """Analyzer that strips known copier headers and retries CRC matching."""

    name = "header_strip"

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """This analyzer needs the actual file — returns empty from name-only analysis.

        Use analyze_file() instead, called by the pipeline.
        """
        return []

    def analyze_file(self, rom_path: Path, dat: DatFile) -> list[Suggestion]:
        """Analyze a ROM file by stripping headers and checking CRC matches."""
        rom_data = _read_rom_data(rom_path)
        if not rom_data:
            return []

        file_size = len(rom_data)
        original_crc = f"{zlib.crc32(rom_data) & 0xFFFFFFFF:08x}"

        # Build CRC → game lookup from DAT
        crc_to_game: dict[str, list] = {}
        size_to_game: dict[int, list] = {}
        for game in dat.games:
            for rom in game.roms:
                if rom.crc:
                    crc_to_game.setdefault(rom.crc.lower(), []).append(game)
                if rom.size:
                    size_to_game.setdefault(rom.size, []).append(game)

        suggestions = []

        for header_size, header_desc in HEADER_SIZES:
            if file_size <= header_size:
                continue

            stripped_size = file_size - header_size
            stripped_data = rom_data[header_size:]
            stripped_crc = f"{zlib.crc32(stripped_data) & 0xFFFFFFFF:08x}"

            # Check if stripped CRC matches any DAT entry
            if stripped_crc in crc_to_game:
                for game in crc_to_game[stripped_crc]:
                    header_bytes = rom_data[:header_size]
                    zero_pct = sum(1 for b in header_bytes if b == 0) * 100 // header_size

                    suggestions.append(Suggestion(
                        dat_game_name=game.name,
                        confidence=0.95,
                        reason=(
                            f"Header detected: {header_desc} ({header_size} bytes, "
                            f"{zero_pct}% zeros). "
                            f"CRC after stripping header matches DAT entry."
                        ),
                        expected_crc=stripped_crc,
                        actual_crc=original_crc,
                        crc_match=True,
                        action="rename",
                    ))

            # Also check if stripped size matches a DAT entry size
            # (potential match even if CRC doesn't match)
            elif stripped_size in size_to_game:
                for game in size_to_game[stripped_size]:
                    expected_crc = game.roms[0].crc if game.roms else ""
                    suggestions.append(Suggestion(
                        dat_game_name=game.name,
                        confidence=0.3,
                        reason=(
                            f"Possible {header_desc} ({header_size} bytes). "
                            f"Size after stripping ({stripped_size}) matches DAT, "
                            f"but CRC still differs."
                        ),
                        expected_crc=expected_crc,
                        actual_crc=stripped_crc,
                        crc_match=False,
                        action="crc_mismatch",
                    ))

        return suggestions


def _read_rom_data(rom_path: Path) -> bytes | None:
    """Read ROM data from a file or zip."""
    try:
        if rom_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(rom_path, "r") as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        return zf.read(info.filename)
        else:
            return rom_path.read_bytes()
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("Could not read ROM file %s: %s", rom_path, e)
    return None
