"""Fuzzy matching between DAT system names and ROM directory names."""

import re

# Common abbreviations and aliases: canonical -> set of variants (all lowercase)
_ALIASES: dict[str, set[str]] = {
    "nes": {"nintendo entertainment system", "famicom", "nes"},
    "snes": {"super nintendo entertainment system", "super famicom", "snes", "super nes"},
    "n64": {"nintendo 64", "n64"},
    "3ds": {"nintendo 3ds", "3ds"},
    "ds": {"nintendo ds", "nds", "ds"},
    "gba": {"game boy advance", "gba"},
    "gbc": {"game boy color", "gbc"},
    "gb": {"game boy", "gb"},
    "genesis": {"mega drive", "genesis", "mega drive - genesis"},
    "ps1": {"playstation", "ps1", "psx", "ps one", "ps one classics"},
    "ps2": {"playstation 2", "ps2"},
    "psp": {"playstation portable", "psp"},
    "ps3": {"playstation 3", "ps3"},
    "pce": {"pc engine", "turbografx-16", "turbografx 16", "pce"},
    "neo geo pocket": {"neogeo pocket", "neo geo pocket", "ngp"},
    "neo geo": {"neogeo", "neo geo", "neo-geo"},
    "sms": {"master system", "sms"},
    "gg": {"game gear", "gg"},
    "2600": {"atari 2600", "2600"},
    "c64": {"commodore 64", "c64"},
    "msx2+": {"msx2+", "msx2 plus"},
    "dreamcast": {"dreamcast", "dc"},
    "saturn": {"saturn", "sega saturn"},
    "sega cd": {"sega cd", "mega cd"},
    "wsc": {"wonderswan color", "wsc"},
}


def match_system(dat_system: str, rom_dirs: list[str]) -> str | None:
    """Find the best matching ROM directory for a DAT system name.

    Returns the ROM directory name, or None if no good match.
    """
    scores = [(d, _score(dat_system, d)) for d in rom_dirs]
    scores.sort(key=lambda x: x[1], reverse=True)
    if scores and scores[0][1] > 0:
        return scores[0][0]
    return None


def match_all(dat_systems: list[str], rom_dirs: list[str]) -> dict[str, str | None]:
    """Match multiple DAT systems to ROM directories.

    Returns a dict of dat_system -> rom_dir (or None).
    """
    return {ds: match_system(ds, rom_dirs) for ds in dat_systems}


def _score(dat_system: str, rom_dir: str) -> float:
    """Score how well a DAT system name matches a ROM directory name."""
    dat_mfr, dat_sys = _split_manufacturer(dat_system.lower())
    rom_mfr, rom_sys = _split_manufacturer(rom_dir.lower())

    # Manufacturer must match (if both have one)
    if dat_mfr and rom_mfr and dat_mfr != rom_mfr:
        return 0.0

    # Strip parenthesized metadata from both
    dat_sys = re.sub(r"\s*\([^)]*\)", "", dat_sys).strip()
    rom_sys = re.sub(r"\s*\([^)]*\)", "", rom_sys).strip()

    # Exact system part match
    if dat_sys == rom_sys:
        return 100.0

    # Alias match: do both system parts resolve to the same canonical?
    dat_canon = _canonicalize(dat_sys)
    rom_canon = _canonicalize(rom_sys)
    if dat_canon and rom_canon and dat_canon == rom_canon:
        return 90.0

    # One contains the other (e.g., "mega drive - genesis" contains "genesis")
    if dat_sys in rom_sys or rom_sys in dat_sys:
        return 80.0

    # Token overlap (only within same manufacturer)
    dat_tokens = _tokenize(dat_sys)
    rom_tokens = _tokenize(rom_sys)
    if not dat_tokens or not rom_tokens:
        return 0.0

    common = dat_tokens & rom_tokens
    if not common:
        return 0.0

    union = dat_tokens | rom_tokens
    score = (len(common) / len(union)) * 70.0

    # Require at least 50% token overlap to be meaningful
    if len(common) / min(len(dat_tokens), len(rom_tokens)) < 0.5:
        return 0.0

    return score


def _split_manufacturer(name: str) -> tuple[str, str]:
    """Split 'Manufacturer - System' into (manufacturer, system).

    Returns ("", name) if no manufacturer prefix found.
    """
    parts = name.split(" - ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", name.strip()


def _canonicalize(system_part: str) -> str | None:
    """Try to map a system name to a canonical alias key."""
    system_part = system_part.lower().strip()
    for canon, variants in _ALIASES.items():
        if system_part in variants or system_part == canon:
            return canon
    return None


def _tokenize(name: str) -> set[str]:
    """Split into meaningful tokens, removing noise words."""
    name = re.sub(r"\b(the|of|and|for)\b", "", name)
    return {t for t in re.split(r"[\s\-/]+", name) if len(t) > 1}
