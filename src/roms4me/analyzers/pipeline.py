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
from roms4me.handlers.registry import get_rom_extensions
from roms4me.analyzers.crc_lookup import CrcLookupAnalyzer
from roms4me.analyzers.header_strip import HeaderStripAnalyzer
from roms4me.analyzers.n64_byteorder import N64ByteOrderAnalyzer
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
    N64ByteOrderAnalyzer(),
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

    # Accepted ROM extensions for this system (used throughout the pipeline)
    accepted_exts: set[str] | None = set(get_rom_extensions(dat.name)) or None

    # Detect inner ROM type for archives and check format vs DAT
    if rom_path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(rom_path) as _zf:
                _entries = [e for e in _zf.infolist() if not e.is_dir()]
                _cands = [e for e in _entries if Path(e.filename).suffix.lower() in accepted_exts] if accepted_exts else _entries
                if not _cands:
                    _cands = _entries
                if _cands:
                    _best = max(_cands, key=lambda e: e.file_size)
                    result.rom_inner_type = Path(_best.filename).suffix.lower().lstrip(".")
                    # Flag if inner format is not the DAT's expected format
                    if accepted_exts:
                        _dat_exts = {Path(rom.name).suffix.lower() for game in dat.games for rom in game.roms if rom.name}
                        _inner_ext = Path(_best.filename).suffix.lower()
                        if _inner_ext and _inner_ext not in _dat_exts:
                            _dat_fmt = ", ".join(sorted(_dat_exts)) or "unknown"
                            result.errors.append(
                                f"Format note: ROM inside zip is {_inner_ext}, "
                                f"DAT expects {_dat_fmt}. "
                                f"May need conversion (e.g. byte-order swap for N64)."
                            )
        except (zipfile.BadZipFile, OSError):
            pass

    # 1. File-based analyzers first — they can confirm matches directly
    for analyzer in FILE_ANALYZERS:
        try:
            suggestions = analyzer.analyze_file(rom_path, dat)
            for s in suggestions:
                if s.dat_game_name not in seen_games:
                    seen_games.add(s.dat_game_name)
                    result.suggestions.append(s)
        except Exception as e:
            msg = f"Analyzer '{analyzer.name}' failed: {e}"
            log.warning("%s on %s", msg, rom_stem)
            result.errors.append(msg)

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
            msg = f"Analyzer '{analyzer.name}' failed: {e}"
            log.warning("%s on %s", msg, rom_stem)
            result.errors.append(msg)

    if not result.suggestions or not verify_crc:
        return result

    # 3. CRC verify name-based candidates (try raw CRC, then header-stripped)
    actual_crc = _compute_crc(rom_path, accepted_exts)
    stripped_crcs = _compute_stripped_crcs(rom_path, accepted_exts)
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


def _compute_stripped_crcs(rom_path: Path, accepted_exts: set[str] | None = None) -> dict[str, str]:
    """Compute CRC32 for header-stripped and byte-order-normalized variants.

    Returns {crc_hex: description} for each variant tried.
    Used by the name-based CRC verify step.
    """
    from roms4me.analyzers.header_strip import HEADER_SIZES, _read_rom_data
    from roms4me.analyzers.n64_byteorder import (
        _FORMAT_LABEL,
        detect_n64_format,
        to_bigendian,
    )

    rom_data = _read_rom_data(rom_path, accepted_exts)
    if not rom_data:
        return {}

    result = {}

    # Header-stripping variants (SNES, NES, Lynx, Atari 7800)
    for header_size, header_desc in HEADER_SIZES:
        if len(rom_data) <= header_size:
            continue
        stripped_crc = f"{zlib.crc32(rom_data[header_size:]) & 0xFFFFFFFF:08x}"
        result[stripped_crc] = header_desc

    # N64 byte-order normalization
    fmt = detect_n64_format(rom_data)
    if fmt and fmt != "bigendian":
        normalized = to_bigendian(rom_data, fmt)
        normalized_crc = f"{zlib.crc32(normalized) & 0xFFFFFFFF:08x}"
        label = _FORMAT_LABEL.get(fmt, fmt)
        result[normalized_crc] = f"N64 {label} → BigEndian conversion"

    return result


def _compute_crc(rom_path: Path, accepted_exts: set[str] | None = None) -> str:
    """Compute CRC32 of the primary ROM file (handles zips).

    For zips, reads the stored CRC from the central directory of the best
    matching entry — avoiding bundled metadata files (READMEs, NFOs, etc.).
    accepted_exts: whitelist of lowercase extensions; falls back to largest file.
    """
    try:
        if rom_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(rom_path, "r") as zf:
                entries = [e for e in zf.infolist() if not e.is_dir()]
                if accepted_exts:
                    candidates = [e for e in entries if Path(e.filename).suffix.lower() in accepted_exts]
                    if not candidates:
                        candidates = entries
                else:
                    candidates = entries
                if candidates:
                    best = max(candidates, key=lambda e: e.file_size)
                    return f"{best.CRC & 0xFFFFFFFF:08x}"
        else:
            data = rom_path.read_bytes()
            return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("Could not compute CRC for %s: %s", rom_path, e)
    return ""
