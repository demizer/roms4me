"""Region map analyzer — maps common region abbreviations to full names.

Handles cases like:
  Spawn (U) → Spawn (USA)
  Mega Man (J) → Mega Man (Japan)
  Sonic (E) → Sonic (Europe)
"""

import re

from roms4me.analyzers.base import Suggestion
from roms4me.models.dat import DatFile

# Common region abbreviations → full names
REGION_MAP = {
    "U": "USA",
    "J": "Japan",
    "E": "Europe",
    "W": "World",
    "F": "France",
    "G": "Germany",
    "S": "Spain",
    "I": "Italy",
    "NL": "Netherlands",
    "SW": "Sweden",
    "A": "Australia",
    "K": "Korea",
    "B": "Brazil",
    "C": "China",
    "HK": "Hong Kong",
    "As": "Asia",
    "En": "En",
    "Ja": "Ja",
    "Fr": "Fr",
    "De": "De",
    "Es": "Es",
    "It": "It",
}


class RegionMapAnalyzer:
    """Analyzer that expands region abbreviations and retries matching."""

    name = "region_map"

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """Try expanding region abbreviations in the ROM name to match DAT entries."""
        expanded = _expand_regions(rom_stem)
        if expanded == rom_stem:
            return []

        # Also try without GoodTools tags like [!], [b], [h], etc.
        cleaned = re.sub(r"\s*\[.*?\]", "", expanded).strip()

        dat_names = {game.name: game for game in dat.games}

        suggestions = []

        # Try exact match with expanded regions
        for candidate in [expanded, cleaned]:
            if candidate in dat_names:
                suggestions.append(Suggestion(
                    dat_game_name=candidate,
                    confidence=0.9,
                    reason=f"Region expanded: {rom_stem} → {candidate}",
                    expected_crc=dat_names[candidate].roms[0].crc if dat_names[candidate].roms else "",
                ))
                return suggestions

        # Try case-insensitive match
        dat_lower = {name.lower(): name for name in dat_names}
        for candidate in [expanded, cleaned]:
            if candidate.lower() in dat_lower:
                real_name = dat_lower[candidate.lower()]
                suggestions.append(Suggestion(
                    dat_game_name=real_name,
                    confidence=0.85,
                    reason=f"Region expanded (case-insensitive): {rom_stem} → {real_name}",
                    expected_crc=dat_names[real_name].roms[0].crc if dat_names[real_name].roms else "",
                ))
                return suggestions

        return suggestions


def _expand_regions(name: str) -> str:
    """Expand region abbreviations in parentheses: (U) → (USA), (J) → (Japan)."""
    def _replace(m):
        tag = m.group(1)
        return f"({REGION_MAP.get(tag, tag)})"

    return re.sub(r"\(([A-Za-z]{1,2})\)", _replace, name)
