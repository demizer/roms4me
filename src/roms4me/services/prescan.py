"""Pre-scan service — cheap compatibility check between DATs and ROM directories.

No hashing involved. Checks file extensions, counts, and filename similarity
to give a quick traffic-light rating per system.
"""

import logging
import re
from pathlib import Path

from roms4me.models.dat import DatFile

log = logging.getLogger(__name__)


class GameMatch:
    """A potential filename-based match between a DAT game and a ROM file."""

    def __init__(self, game_name: str, description: str, matched_file: str) -> None:
        self.game_name = game_name
        self.description = description
        self.matched_file = matched_file  # empty string if no match
        self.unmatched = False  # True if this is a ROM file with no DAT match
        self.note = ""  # Explanation for unmatched items


class PrescanResult:
    """Result of pre-scanning a system's DAT against its ROM directory."""

    def __init__(self, system: str) -> None:
        self.system = system
        self.dat_game_count: int = 0
        self.dat_extensions: set[str] = set()
        self.rom_file_count: int = 0
        self.rom_extensions: set[str] = set()
        self.rom_dir: str = ""
        self.name_matches: int = 0
        self.rating: str = "red"  # green, yellow, red
        self.reason: str = ""
        self.games: list[GameMatch] = []

    def to_dict(self) -> dict:
        """Serialize for API response."""
        return {
            "system": self.system,
            "dat_game_count": self.dat_game_count,
            "dat_extensions": sorted(self.dat_extensions),
            "rom_file_count": self.rom_file_count,
            "rom_extensions": sorted(self.rom_extensions),
            "rom_dir": self.rom_dir,
            "name_matches": self.name_matches,
            "rating": self.rating,
            "reason": self.reason,
        }


def prescan_system(dat: DatFile, rom_dir: Path) -> PrescanResult:
    """Pre-scan a system: compare DAT expectations vs ROM directory contents."""
    result = PrescanResult(dat.name)
    result.rom_dir = str(rom_dir)

    # Analyze DAT
    result.dat_game_count = len(dat.games)
    for game in dat.games:
        for rom in game.roms:
            ext = Path(rom.name).suffix.lower()
            if ext:
                result.dat_extensions.add(ext)

    # Analyze ROM directory
    rom_files = [f for f in rom_dir.iterdir() if f.is_file()]
    result.rom_file_count = len(rom_files)
    rom_names: dict[str, Path] = {}
    for f in rom_files:
        ext = f.suffix.lower()
        if ext:
            result.rom_extensions.add(ext)
        rom_names[_normalize_name(f.stem)] = f

    # Check extension compatibility
    ext_overlap = result.dat_extensions & result.rom_extensions
    dat_has_zips = any(
        ext in result.rom_extensions for ext in (".zip", ".7z")
    )

    # Build normalized ROM name -> list of original filenames
    # Multiple ROMs can normalize to the same key (e.g., (U) and (USA))
    rom_lookup: dict[str, list[str]] = {}
    for f in rom_files:
        norm = _normalize_name(f.stem)
        rom_lookup.setdefault(norm, []).append(f.name)

    # Try filename matching per game (cheap, no hashing)
    match_count = 0
    matched_rom_files: set[str] = set()
    for game in dat.games:
        norm_game = _normalize_name(game.name)
        candidates = rom_lookup.get(norm_game, [])
        # Pick the best candidate — prefer one not already matched
        matched_file = ""
        for c in candidates:
            if c not in matched_rom_files:
                matched_file = c
                break
        if not matched_file and candidates:
            matched_file = candidates[0]  # Fall back to first if all taken
        if matched_file:
            match_count += 1
            matched_rom_files.add(matched_file)
        result.games.append(GameMatch(
            game_name=game.name,
            description=game.description,
            matched_file=matched_file,
        ))
    result.name_matches = match_count

    # Find ROM files that didn't match any DAT entry — explain why
    dat_game_names = [game.name for game in dat.games]
    for f in rom_files:
        if f.name not in matched_rom_files:
            closest, reason = find_closest_dat_match(f.stem, dat_game_names)
            gm = GameMatch(
                game_name=f.stem,
                description=f.stem,
                matched_file=f.name,
            )
            gm.unmatched = True
            gm.note = reason
            result.games.append(gm)

    # Rate the match
    result.rating, result.reason = _rate_match(result, ext_overlap, dat_has_zips)

    return result


def _rate_match(
    result: PrescanResult,
    ext_overlap: set[str],
    dat_has_zips: bool,
) -> tuple[str, str]:
    """Rate the DAT/ROM compatibility and return (rating, reason)."""
    if result.rom_file_count == 0:
        return "red", "ROM directory is empty"

    if result.dat_game_count == 0:
        return "red", "DAT file has no games"

    # Check for format mismatch (e.g., PKG DAT vs CHD ROMs)
    rom_is_disc = bool(result.rom_extensions & {".chd", ".iso", ".cue", ".bin", ".cdi", ".cso"})
    dat_is_pkg = bool(result.dat_extensions & {".pkg", ".rap"})
    dat_is_disc = bool(result.dat_extensions & {".chd", ".iso", ".cue", ".bin", ".img"})

    if dat_is_pkg and rom_is_disc:
        return "red", "DAT is for digital store packages but ROMs are disc dumps. Try Redump DATs."

    if rom_is_disc and not dat_is_disc and not dat_is_pkg:
        return "yellow", "ROMs are disc images but DAT expects cartridge dumps"

    # Extension compatibility
    if not ext_overlap and not dat_has_zips:
        # No extension overlap and ROMs aren't zipped
        return "red", (
            f"No extension match. DAT expects {_fmt_exts(result.dat_extensions)}, "
            f"ROMs have {_fmt_exts(result.rom_extensions)}"
        )

    # Name matching
    match_pct = (result.name_matches / result.dat_game_count * 100) if result.dat_game_count else 0

    if match_pct > 20:
        return "green", f"{result.name_matches} filename matches ({match_pct:.0f}% of DAT)"
    elif match_pct > 0 or dat_has_zips:
        if result.name_matches > 0:
            return "yellow", (
                f"Only {result.name_matches} filename matches ({match_pct:.0f}% of DAT). "
                "CRC scan may find more."
            )
        else:
            return "yellow", (
                "No filename matches but extensions are compatible. "
                "CRC scan may find matches."
            )
    else:
        return "red", (
            f"No filename matches. DAT expects {_fmt_exts(result.dat_extensions)}, "
            f"ROMs have {_fmt_exts(result.rom_extensions)}"
        )


def find_closest_dat_match(rom_stem: str, dat_names: list[str]) -> tuple[str, str]:
    """Find the closest DAT game name to a ROM filename and explain the mismatch.

    Returns (closest_dat_name, reason) or ("", "No similar DAT entry found").
    """
    rom_norm = _normalize_name(rom_stem)
    rom_base = _extract_base_name(rom_stem)

    best_name = ""
    best_score = 0.0
    best_reason = ""

    for dat_name in dat_names:
        dat_base = _extract_base_name(dat_name)

        # Exact base name match — differs only in tags
        if rom_base and dat_base and rom_base == dat_base:
            rom_tags = _extract_tags(rom_stem)
            dat_tags = _extract_tags(dat_name)
            diffs = []
            if rom_tags != dat_tags:
                only_rom = rom_tags - dat_tags
                only_dat = dat_tags - rom_tags
                if only_rom:
                    diffs.append(f"ROM has: {', '.join(sorted(only_rom))}")
                if only_dat:
                    diffs.append(f"DAT has: {', '.join(sorted(only_dat))}")
            reason = "; ".join(diffs) if diffs else "Different naming convention"
            return dat_name, f"Similar: {dat_name} — {reason}"

        # Fuzzy: check token overlap
        dat_norm = _normalize_name(dat_name)
        if not rom_norm or not dat_norm:
            continue
        rom_tokens = set(rom_norm.split())
        dat_tokens = set(dat_norm.split())
        if not rom_tokens or not dat_tokens:
            continue
        common = rom_tokens & dat_tokens
        score = len(common) / max(len(rom_tokens), len(dat_tokens))
        if score > best_score:
            best_score = score
            best_name = dat_name
            if score > 0.5:
                best_reason = f"Similar: {dat_name}"

    if best_reason:
        return best_name, best_reason
    return "", "No similar DAT entry found"


def _extract_base_name(name: str) -> str:
    """Extract the base game name before any parenthesized/bracketed tags."""
    # "Mega Man X (USA) [!]" -> "mega man x"
    base = re.sub(r"\s*[\[\(].*", "", name).strip().lower()
    return re.sub(r"[^a-z0-9 ]", "", base).strip()


def _extract_tags(name: str) -> set[str]:
    """Extract all parenthesized and bracketed tags from a name."""
    return set(re.findall(r"[\[\(]([^\]\)]+)[\]\)]", name))


def _normalize_name(name: str) -> str:
    """Normalize a game name for fuzzy comparison."""
    name = name.lower()
    # Remove common tags: (USA), [!], (Rev 1), etc.
    name = re.sub(r"\s*[\[\(][^\]\)]*[\]\)]", "", name)
    # Remove non-alphanumeric
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _fmt_exts(exts: set[str]) -> str:
    """Format a set of extensions for display."""
    if not exts:
        return "(none)"
    return ", ".join(sorted(exts))
