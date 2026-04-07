"""Unified name matching — shared utilities and analyzer.

All ROM-to-DAT name matching flows through this module:
- NameMatchAnalyzer: pipeline analyzer for full analysis
- Utility functions: used by prescan and other services

Matching steps (highest confidence first):
1. Region expansion + exact full-name match
2. Region expansion + case-insensitive full-name match
3. Exact base-name match (tags stripped)
4. Word boundary: ROM base found in DAT name
5. Word boundary: DAT base found in ROM name
"""

import re

from roms4me.analyzers.base import Suggestion
from roms4me.models.dat import DatFile, GameEntry

# ---------------------------------------------------------------------------
# Region abbreviation table
# ---------------------------------------------------------------------------

REGION_MAP: dict[str, str] = {
    "U": "USA", "J": "Japan", "E": "Europe", "W": "World",
    "F": "France", "G": "Germany", "S": "Spain", "I": "Italy",
    "NL": "Netherlands", "SW": "Sweden", "A": "Australia",
    "K": "Korea", "B": "Brazil", "C": "China",
    "HK": "Hong Kong", "As": "Asia",
    "En": "En", "Ja": "Ja", "Fr": "Fr", "De": "De", "Es": "Es", "It": "It",
}


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def expand_regions(name: str) -> str:
    """Expand region abbreviations in parentheses: (U) -> (USA), (J) -> (Japan)."""
    def _replace(m: re.Match[str]) -> str:
        tag = m.group(1)
        return f"({REGION_MAP.get(tag, tag)})"
    return re.sub(r"\(([A-Za-z]{1,2})\)", _replace, name)


def extract_base(name: str) -> str:
    """Extract the base game name before any parenthesized/bracketed tags.

    "Gran Turismo 4 (USA) (v2.00)" -> "Gran Turismo 4"
    """
    return re.sub(r"\s*[\[\(].*", "", name).strip()


def extract_tags(name: str) -> set[str]:
    """Extract all parenthesized and bracketed tags from a name.

    "Sonic (USA) [!]" -> {"USA", "!"}
    """
    return set(re.findall(r"[\[\(]([^\]\)]+)[\]\)]", name))


def normalize_name(name: str) -> str:
    """Normalize a game name for exact lookup (lowercase, tags and symbols stripped).

    "Gran Turismo 4 (USA)" -> "granturismo4"
    """
    name = name.lower()
    name = re.sub(r"\s*[\[\(][^\]\)]*[\]\)]", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _word_match(needle: str, haystack: str) -> bool:
    """Check if needle appears in haystack at a word boundary.

    Prevents "gon" matching inside "dragon".
    """
    return bool(re.search(
        r"(?:^|[\s\-,:])" + re.escape(needle) + r"(?:$|[\s\-,:])",
        haystack,
    ))


# ---------------------------------------------------------------------------
# Analyzer — pipeline integration
# ---------------------------------------------------------------------------

def match_names(rom_stem: str, dat: DatFile) -> list[Suggestion]:
    """Unified name matching against a DAT.

    Returns up to 5 suggestions sorted by confidence.
    """
    suggestions: list[Suggestion] = []
    seen: set[str] = set()

    # Pre-compute ROM name variants
    expanded = expand_regions(rom_stem)
    regions_changed = (expanded != rom_stem)
    cleaned = re.sub(r"\s*\[.*?\]", "", expanded).strip()  # strip GoodTools tags
    base = extract_base(rom_stem)
    if not base or len(base) < 3:
        return []
    base_lower = base.lower()

    # Build lookup structures
    dat_by_name: dict[str, GameEntry] = {game.name: game for game in dat.games}
    dat_lower: dict[str, str] = {name.lower(): name for name in dat_by_name}

    def _add(game: GameEntry, confidence: float, reason: str) -> None:
        if game.name not in seen:
            seen.add(game.name)
            suggestions.append(Suggestion(
                dat_game_name=game.name,
                confidence=confidence,
                reason=reason,
                expected_crc=game.roms[0].crc if game.roms else "",
            ))

    # 1. Exact full-name match (case-insensitive)
    for candidate in (rom_stem, cleaned):
        low = candidate.lower()
        if low in dat_lower:
            real = dat_lower[low]
            _add(dat_by_name[real], 0.95, f'Exact name match: "{real}"')

    # 2. Region expansion (only when expansion actually changed the name)
    if regions_changed:
        for candidate in (expanded, cleaned):
            if candidate in dat_by_name:
                _add(dat_by_name[candidate], 0.9,
                     f"Region expanded: {rom_stem} → {candidate}")
        for candidate in (expanded, cleaned):
            low = candidate.lower()
            if low in dat_lower:
                real = dat_lower[low]
                _add(dat_by_name[real], 0.85,
                     f"Region expanded (case-insensitive): {rom_stem} → {real}")

    # 3–5. Base name matching
    for game in dat.games:
        if game.name in seen:
            continue
        game_base = extract_base(game.name).lower()
        if not game_base:
            continue

        if base_lower == game_base:
            _add(game, 0.85, f'Exact base name match: "{base}"')
        elif _word_match(base_lower, game_base):
            coverage = len(base_lower) / len(game_base)
            _add(game, min(0.7, coverage),
                 f'ROM name "{base}" found in "{game.name}"')
        elif _word_match(game_base, base_lower):
            coverage = len(game_base) / len(base_lower)
            _add(game, min(0.5, coverage),
                 f'DAT name "{game.name}" found in ROM name "{base}"')

    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    return suggestions[:5]


class NameMatchAnalyzer:
    """Unified name-based analyzer — combines region expansion and base-name matching."""

    name = "name_match"

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """Find DAT games that match the ROM filename."""
        return match_names(rom_stem, dat)


# ---------------------------------------------------------------------------
# Prescan helper
# ---------------------------------------------------------------------------

def find_closest_match(rom_stem: str, dat_names: list[str]) -> tuple[str, str]:
    """Find the closest DAT game name to a ROM filename and explain the mismatch.

    Used by prescan for unmatched ROM diagnostics.
    Returns (closest_dat_name, reason) or ("", "No similar DAT entry found").
    """
    rom_base = re.sub(r"[^a-z0-9 ]", "", extract_base(rom_stem).lower()).strip()

    best_name = ""
    best_score = 0.0
    best_reason = ""

    for dat_name in dat_names:
        dat_base = re.sub(r"[^a-z0-9 ]", "", extract_base(dat_name).lower()).strip()

        # Exact base name match — differs only in tags
        if rom_base and dat_base and rom_base == dat_base:
            rom_tags = extract_tags(rom_stem)
            dat_tags = extract_tags(dat_name)
            diffs: list[str] = []
            if rom_tags != dat_tags:
                only_rom = rom_tags - dat_tags
                only_dat = dat_tags - rom_tags
                if only_rom:
                    diffs.append(f"ROM has: {', '.join(sorted(only_rom))}")
                if only_dat:
                    diffs.append(f"DAT has: {', '.join(sorted(only_dat))}")
            reason = "; ".join(diffs) if diffs else "Different naming convention"
            return dat_name, f"Similar: {dat_name} — {reason}"

        # Fuzzy: token overlap on normalized names
        rom_norm = normalize_name(rom_stem)
        dat_norm = normalize_name(dat_name)
        if not rom_norm or not dat_norm:
            continue
        # Use character-level comparison since normalize strips spaces
        overlap = len(set(rom_norm) & set(dat_norm)) / max(len(set(rom_norm)), len(set(dat_norm)))
        if overlap > best_score:
            best_score = overlap
            best_name = dat_name
            if overlap > 0.7:
                best_reason = f"Similar: {dat_name}"

    if best_reason:
        return best_name, best_reason
    return "", "No similar DAT entry found"
