"""ROM scanner and verifier using CRC-based matching."""

import logging
import zlib
import zipfile
from pathlib import Path

from roms4me.models.dat import DatFile, RomEntry
from roms4me.models.scan import GameScanResult, RomScanResult, RomStatus

log = logging.getLogger(__name__)


def scan_roms(dat: DatFile, rom_dir: Path) -> list[GameScanResult]:
    """Scan a ROM directory against a DAT file using CRC matching.

    Builds a CRC lookup from the DAT, then hashes every file in the ROM
    directory (loose files and files inside zips) to find matches.
    """
    # Build CRC -> (game_index, rom_entry) lookup from DAT
    crc_lookup: dict[str, list[tuple[int, RomEntry]]] = {}
    for i, game in enumerate(dat.games):
        for rom in game.roms:
            if rom.crc:
                crc_lookup.setdefault(rom.crc.lower(), []).append((i, rom))

    # Track which games/roms we've found
    # game_index -> { rom_name -> (found_file, status) }
    found: dict[int, dict[str, tuple[str, RomStatus]]] = {}

    # Scan all files in the ROM directory
    file_count = 0
    for file_path in rom_dir.iterdir():
        if file_path.is_file():
            if file_path.suffix.lower() == ".zip":
                file_count += _scan_zip(file_path, crc_lookup, found)
            else:
                file_count += _scan_loose(file_path, crc_lookup, found)

    log.info("Scanned %d files in %s", file_count, rom_dir)

    # Build results for every game in the DAT
    results: list[GameScanResult] = []
    for i, game in enumerate(dat.games):
        game_found = found.get(i, {})
        rom_results: list[RomScanResult] = []

        for rom in game.roms:
            if rom.name in game_found:
                found_file, status = game_found[rom.name]
                rom_results.append(RomScanResult(
                    name=found_file,
                    expected_name=rom.name,
                    status=status,
                    size=rom.size,
                    expected_size=rom.size,
                ))
            else:
                rom_results.append(RomScanResult(
                    name="",
                    expected_name=rom.name,
                    status=RomStatus.MISSING,
                    expected_size=rom.size,
                ))

        overall = _overall_status(rom_results)
        results.append(GameScanResult(
            name=game.name,
            description=game.description,
            file_name=game_found.get(game.roms[0].name, ("", RomStatus.MISSING))[0] if game.roms else "",
            expected_file_name=f"{game.name}.zip",
            status=overall,
            roms=rom_results,
        ))

    return results


def _scan_zip(zip_path: Path, crc_lookup: dict, found: dict) -> int:
    """Scan files inside a zip archive. Returns number of files checked."""
    count = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                count += 1
                crc = f"{info.CRC:08x}"
                _match_crc(crc, f"{zip_path.name}/{info.filename}", crc_lookup, found)
    except (zipfile.BadZipFile, OSError):
        log.warning("Bad zip file: %s", zip_path)
    return count


def _scan_loose(file_path: Path, crc_lookup: dict, found: dict) -> int:
    """Scan a loose (non-zip) ROM file. Returns 1."""
    try:
        data = file_path.read_bytes()
        crc = f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
        _match_crc(crc, file_path.name, crc_lookup, found)
    except OSError:
        log.warning("Could not read file: %s", file_path)
    return 1


def _match_crc(crc: str, source_name: str, crc_lookup: dict, found: dict) -> None:
    """Check a CRC against the lookup and record matches."""
    matches = crc_lookup.get(crc)
    if not matches:
        return
    for game_idx, rom_entry in matches:
        game_found = found.setdefault(game_idx, {})
        if rom_entry.name not in game_found:
            game_found[rom_entry.name] = (source_name, RomStatus.OK)


def _overall_status(roms: list[RomScanResult]) -> RomStatus:
    """Determine overall game status from individual ROM results."""
    if not roms:
        return RomStatus.OK
    statuses = {r.status for r in roms}
    if statuses == {RomStatus.OK}:
        return RomStatus.OK
    if statuses == {RomStatus.MISSING}:
        return RomStatus.MISSING
    # Mix of ok and missing = incomplete
    return RomStatus.BAD_DUMP
