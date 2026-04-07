"""Direct CRC lookup analyzer — the simplest and most reliable check.

Looks up the ROM's CRC directly in the DAT. The CRC is computed once by
the pipeline and passed in — this analyzer does no I/O of its own.

For CHD files where CRC computation fails (CD codecs), falls back to
reading the SHA-1 from the CHD header and matching against DAT SHA-1.
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
        """Look up CRC in the DAT. Falls back to SHA-1 for CHD files."""
        if crc:
            suggestions = self._lookup_crc(crc, dat)
            if suggestions:
                return suggestions

        # CHD fallback: read SHA-1 from header, match against DAT SHA-1
        if not crc and rom_path.suffix.lower() == ".chd":
            return self._lookup_chd_sha1(rom_path, dat)

        return self._lookup_crc(crc, dat) if crc else []

    def _lookup_crc(self, crc: str, dat: DatFile) -> list[Suggestion]:
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

    def _lookup_chd_sha1(self, rom_path: Path, dat: DatFile) -> list[Suggestion]:
        from roms4me.analyzers.chd import read_chd_sha1
        sha1 = read_chd_sha1(rom_path)
        if not sha1:
            return []

        suggestions = []
        for game in dat.games:
            for rom in game.roms:
                if rom.sha1 and rom.sha1.lower() == sha1:
                    suggestions.append(Suggestion(
                        dat_game_name=game.name,
                        confidence=1.0,
                        reason=f"SHA-1 match from CHD header ({sha1[:12]}…)",
                        expected_crc=rom.crc.lower() if rom.crc else "",
                        actual_crc=sha1,
                        crc_match=True,
                        action="rename",
                    ))
        return suggestions
