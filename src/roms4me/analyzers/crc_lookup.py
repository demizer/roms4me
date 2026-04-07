"""Direct CRC lookup analyzer — the simplest and most reliable check.

Looks up the ROM's CRC directly in the DAT. The CRC is computed once by
the pipeline and passed in — this analyzer does no I/O of its own.
"""

from pathlib import Path

from roms4me.analyzers.base import Suggestion
from roms4me.models.dat import DatFile


class CrcLookupAnalyzer:
    """Analyzer that does a direct CRC lookup against all DAT entries."""

    name = "crc_lookup"

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """Name-only analysis — not applicable for CRC lookup."""
        return []

    def analyze_file(self, rom_path: Path, dat: DatFile, crc: str = "") -> list[Suggestion]:
        """Look up CRC in the DAT. CRC is provided by the pipeline."""
        if not crc:
            return []

        suggestions = []
        for game in dat.games:
            for rom in game.roms:
                if rom.crc and rom.crc.lower() == crc:
                    suggestions.append(Suggestion(
                        dat_game_name=game.name,
                        confidence=1.0,
                        reason="Direct CRC match",
                        expected_crc=rom.crc.lower(),
                        actual_crc=crc,
                        crc_match=True,
                        action="rename",
                    ))

        return suggestions
