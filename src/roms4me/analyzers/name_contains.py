"""Name-contains analyzer — finds DAT entries that contain the ROM's base name.

Handles cases like:
  Spawn (U) → Todd McFarlane's Spawn - The Video Game (USA)
  Tetris (U) → Tetris & Dr. Mario (USA)
"""

import re

from roms4me.analyzers.base import Suggestion
from roms4me.models.dat import DatFile


class NameContainsAnalyzer:
    """Analyzer that checks if the ROM's base name appears within DAT entries."""

    name = "name_contains"

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """Find DAT games whose name contains the ROM's base name."""
        base = _extract_base(rom_stem)
        if not base or len(base) < 3:
            return []

        base_lower = base.lower()
        suggestions = []

        for game in dat.games:
            game_base = _extract_base(game.name).lower()
            if not game_base:
                continue

            # ROM base contained in DAT name (word boundary match)
            if _word_match(base_lower, game_base) and base_lower != game_base:
                coverage = len(base_lower) / len(game_base)
                suggestions.append(Suggestion(
                    dat_game_name=game.name,
                    confidence=min(0.7, coverage),
                    reason=f'ROM name "{base}" found in "{game.name}"',
                    expected_crc=game.roms[0].crc if game.roms else "",
                ))

            # DAT base contained in ROM name (word boundary match)
            elif _word_match(game_base, base_lower) and game_base != base_lower:
                coverage = len(game_base) / len(base_lower)
                suggestions.append(Suggestion(
                    dat_game_name=game.name,
                    confidence=min(0.5, coverage),
                    reason=f'DAT name "{game.name}" found in ROM name "{base}"',
                    expected_crc=game.roms[0].crc if game.roms else "",
                ))

        # Sort by confidence, highest first
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:5]  # Limit to top 5


def _word_match(needle: str, haystack: str) -> bool:
    """Check if needle appears in haystack at a word boundary.

    Prevents 'gon' matching inside 'dragon'.
    """
    return bool(re.search(r"(?:^|[\s\-,:])" + re.escape(needle) + r"(?:$|[\s\-,:])", haystack))


def _extract_base(name: str) -> str:
    """Extract the base game name before any tags."""
    return re.sub(r"\s*[\[\(].*", "", name).strip()
