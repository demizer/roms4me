"""Direct CRC lookup analyzer — the simplest and most reliable check.

Computes the ROM's CRC and looks it up directly in the DAT.
This catches all exact matches regardless of filename.
"""

import logging
import zipfile
import zlib
from pathlib import Path

from roms4me.analyzers.base import Suggestion
from roms4me.models.dat import DatFile

log = logging.getLogger(__name__)


class CrcLookupAnalyzer:
    """Analyzer that does a direct CRC lookup against all DAT entries."""

    name = "crc_lookup"

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """Name-only analysis — not applicable for CRC lookup."""
        return []

    def analyze_file(self, rom_path: Path, dat: DatFile) -> list[Suggestion]:
        """Compute ROM CRC and look it up in the DAT."""
        actual_crc = _compute_crc(rom_path)
        if not actual_crc:
            return []

        suggestions = []
        for game in dat.games:
            for rom in game.roms:
                if rom.crc and rom.crc.lower() == actual_crc:
                    suggestions.append(Suggestion(
                        dat_game_name=game.name,
                        confidence=1.0,
                        reason="Direct CRC match",
                        expected_crc=rom.crc.lower(),
                        actual_crc=actual_crc,
                        crc_match=True,
                        action="rename",
                    ))

        return suggestions


def _compute_crc(rom_path: Path) -> str:
    """Compute CRC32 of a ROM file (handles zips)."""
    try:
        if rom_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(rom_path, "r") as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        return f"{info.CRC:08x}"
        else:
            data = rom_path.read_bytes()
            return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("Could not compute CRC for %s: %s", rom_path, e)
    return ""
