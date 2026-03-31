"""Analyzer pipeline — runs all heuristics then verifies with CRC.

Analyzer types:
- Name-based: analyze(rom_stem, dat) → suggestions from filename alone
- File-based: analyze_file(rom_path, dat) → suggestions that need file access (headers, CRC)
"""

import logging
import zipfile
import zlib
from pathlib import Path

from roms4me.analyzers.base import AnalysisResult, Suggestion
from roms4me.analyzers.crc_lookup import CrcLookupAnalyzer
from roms4me.analyzers.header_strip import HeaderStripAnalyzer
from roms4me.analyzers.name_contains import NameContainsAnalyzer
from roms4me.analyzers.region_map import RegionMapAnalyzer
from roms4me.models.dat import DatFile

log = logging.getLogger(__name__)

# Name-based analyzers — fast, work on filename only
NAME_ANALYZERS = [
    RegionMapAnalyzer(),
    NameContainsAnalyzer(),
]

# File-based analyzers — need to read ROM data
FILE_ANALYZERS = [
    CrcLookupAnalyzer(),
    HeaderStripAnalyzer(),
]


def analyze_rom(
    rom_path: Path,
    dat: DatFile,
    verify_crc: bool = True,
) -> AnalysisResult:
    """Run all analyzers on a ROM file, then optionally verify CRC.

    Pipeline order:
    1. File-based analyzers (header strip) — these can find confirmed matches
    2. Name-based analyzers (region map, name contains) — find candidates
    3. CRC verify the name-based candidates

    Returns an AnalysisResult with ranked suggestions.
    """
    result = AnalysisResult(rom_file=rom_path.name)
    rom_stem = rom_path.stem
    seen_games: set[str] = set()

    # 1. File-based analyzers first — they can confirm matches directly
    for analyzer in FILE_ANALYZERS:
        try:
            suggestions = analyzer.analyze_file(rom_path, dat)
            for s in suggestions:
                if s.dat_game_name not in seen_games:
                    seen_games.add(s.dat_game_name)
                    result.suggestions.append(s)
        except Exception as e:
            log.warning("Analyzer %s failed for %s: %s", analyzer.name, rom_stem, e)

    # If header strip found a confirmed match, return early
    if any(s.crc_match is True for s in result.suggestions):
        result.suggestions.sort(key=lambda s: (s.crc_match is True, s.confidence), reverse=True)
        return result

    # 2. Name-based analyzers
    for analyzer in NAME_ANALYZERS:
        try:
            suggestions = analyzer.analyze(rom_stem, dat)
            for s in suggestions:
                if s.dat_game_name not in seen_games:
                    seen_games.add(s.dat_game_name)
                    result.suggestions.append(s)
        except Exception as e:
            log.warning("Analyzer %s failed for %s: %s", analyzer.name, rom_stem, e)

    if not result.suggestions or not verify_crc:
        return result

    # 3. CRC verify name-based candidates (try raw CRC, then header-stripped)
    actual_crc = _compute_crc(rom_path)
    stripped_crcs = _compute_stripped_crcs(rom_path)
    if not actual_crc:
        return result

    for s in result.suggestions:
        if s.crc_match is not None:
            continue  # Already verified by file-based analyzer
        s.actual_crc = actual_crc
        if s.expected_crc:
            expected = s.expected_crc.lower()
            if actual_crc == expected:
                s.crc_match = True
                s.confidence = 1.0
                s.action = "rename"
            elif expected in stripped_crcs:
                s.crc_match = True
                s.confidence = 0.95
                s.actual_crc = expected  # the stripped CRC that matched
                s.reason += f" (after stripping {stripped_crcs[expected]} header)"
                s.action = "rename"
            else:
                s.crc_match = False
                s.action = "crc_mismatch"

    # Sort: confirmed CRC matches first, then by confidence
    result.suggestions.sort(key=lambda s: (s.crc_match is True, s.confidence), reverse=True)
    return result


def _compute_stripped_crcs(rom_path: Path) -> dict[str, str]:
    """Compute CRC32 for each header-stripped variant. Returns {crc: header_desc}."""
    from roms4me.analyzers.header_strip import HEADER_SIZES, _read_rom_data

    rom_data = _read_rom_data(rom_path)
    if not rom_data:
        return {}

    result = {}
    for header_size, header_desc in HEADER_SIZES:
        if len(rom_data) <= header_size:
            continue
        stripped_crc = f"{zlib.crc32(rom_data[header_size:]) & 0xFFFFFFFF:08x}"
        result[stripped_crc] = header_desc
    return result


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
