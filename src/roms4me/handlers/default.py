"""Default handler — CRC-based matching for single-ROM-per-game systems.

Works for most cartridge-based consoles: SNES, NES, Game Boy, Genesis, etc.
ROMs can be loose files or zipped (one ROM per zip).
"""

import logging
import time
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

from roms4me.handlers.base import ProgressCallback
from roms4me.models.dat import DatFile, RomEntry
from roms4me.models.scan import GameScanResult, RomScanResult, RomStatus

log = logging.getLogger(__name__)

# Files larger than this get chunked hashing with a progress bar
_LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50MB


def _human_size(nbytes: int) -> str:
    """Format bytes as human-readable size."""
    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


class DefaultHandler:
    name = "default"
    extensions = [".zip", ".7z"]

    def scan(
        self,
        dat: DatFile,
        rom_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> list[GameScanResult]:
        """CRC-based scan: hash every file, match against DAT entries."""
        crc_lookup = _build_crc_lookup(dat)
        found: dict[int, dict[str, tuple[str, RomStatus]]] = {}

        files = [f for f in rom_dir.iterdir() if f.is_file()]
        total_files = len(files)

        for i, file_path in enumerate(files):
            file_size = file_path.stat().st_size
            size_str = _human_size(file_size)
            t0 = time.monotonic()

            if file_path.suffix.lower() == ".zip":
                _scan_zip(file_path, crc_lookup, found)
            else:
                if file_size > _LARGE_FILE_THRESHOLD and on_progress:
                    # Chunked hashing with progress bar for large files
                    _scan_loose_chunked(
                        file_path, crc_lookup, found,
                        lambda pct, name=file_path.name, sz=size_str: on_progress(
                            f"    {_progress_bar(pct)} {pct}% {name} ({sz})", True
                        ),
                    )
                else:
                    _scan_loose(file_path, crc_lookup, found)

            elapsed = time.monotonic() - t0

            # Log every file (permanent line)
            if on_progress:
                tag = f" ({elapsed:.1f}s)" if elapsed >= 1.0 else ""
                on_progress(f"    {i + 1}/{total_files}: {file_path.name} ({size_str}){tag}", False)

        log.info("Scanned %d files in %s", total_files, rom_dir)
        return _build_results(dat, found)

    def fix(self, dat: DatFile, rom_dir: Path, output_dir: Path) -> int:
        """Rename and zip ROMs to match DAT names."""
        crc_lookup = _build_crc_lookup(dat)
        found: dict[int, dict[str, tuple[str, RomStatus]]] = {}

        for file_path in rom_dir.iterdir():
            if file_path.is_file():
                if file_path.suffix.lower() == ".zip":
                    _scan_zip(file_path, crc_lookup, found)
                else:
                    _scan_loose(file_path, crc_lookup, found)

        output_dir.mkdir(parents=True, exist_ok=True)
        fixed = 0
        for i, game in enumerate(dat.games):
            game_found = found.get(i)
            if not game_found:
                continue
            if len(game_found) != len(game.roms):
                continue

            out_zip = output_dir / f"{game.name}.zip"
            if out_zip.exists():
                continue

            with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for rom in game.roms:
                    source_name, _ = game_found[rom.name]
                    data = _read_source(rom_dir, source_name)
                    if data is not None:
                        zf.writestr(rom.name, data)
            fixed += 1
            log.info("Fixed: %s", game.name)

        return fixed


# --- Progress bar ---


def _progress_bar(pct: int, width: int = 20) -> str:
    filled = round(width * pct / 100)
    return "\u2588" * filled + "\u2591" * (width - filled)


# --- Shared helpers ---


def _build_crc_lookup(dat: DatFile) -> dict[str, list[tuple[int, RomEntry]]]:
    """Build CRC -> [(game_index, rom_entry)] lookup from a DAT."""
    lookup: dict[str, list[tuple[int, RomEntry]]] = {}
    for i, game in enumerate(dat.games):
        for rom in game.roms:
            if rom.crc:
                lookup.setdefault(rom.crc.lower(), []).append((i, rom))
    return lookup


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
    """Scan a loose ROM file. Returns 1."""
    try:
        data = file_path.read_bytes()
        crc = f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
        _match_crc(crc, file_path.name, crc_lookup, found)
    except OSError:
        log.warning("Could not read file: %s", file_path)
    return 1


def _scan_loose_chunked(
    file_path: Path,
    crc_lookup: dict,
    found: dict,
    on_pct: Callable[[int], None],
) -> int:
    """Hash a large file in 4MB chunks, calling on_pct with percentage."""
    chunk_size = 4 * 1024 * 1024
    try:
        file_size = file_path.stat().st_size
        crc_val = 0
        read_bytes = 0
        last_pct = -1
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                crc_val = zlib.crc32(chunk, crc_val)
                read_bytes += len(chunk)
                pct = round(read_bytes / file_size * 100) if file_size else 100
                if pct != last_pct:
                    on_pct(pct)
                    last_pct = pct
        crc = f"{crc_val & 0xFFFFFFFF:08x}"
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


def _build_results(dat: DatFile, found: dict) -> list[GameScanResult]:
    """Build GameScanResult list from DAT + found matches."""
    results: list[GameScanResult] = []
    for i, game in enumerate(dat.games):
        game_found = found.get(i, {})
        rom_results: list[RomScanResult] = []

        for rom in game.roms:
            if rom.name in game_found:
                source_name, status = game_found[rom.name]
                rom_results.append(RomScanResult(
                    name=source_name,
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
        first_rom_source = ""
        if game.roms and game.roms[0].name in game_found:
            first_rom_source = game_found[game.roms[0].name][0]

        results.append(GameScanResult(
            name=game.name,
            description=game.description,
            file_name=first_rom_source,
            expected_file_name=f"{game.name}.zip",
            status=overall,
            roms=rom_results,
        ))
    return results


def _read_source(rom_dir: Path, source_name: str) -> bytes | None:
    """Read ROM data from a source (loose file or zip_name/inner_name)."""
    if "/" in source_name:
        zip_name, inner_name = source_name.split("/", 1)
        zip_path = rom_dir / zip_name
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                return zf.read(inner_name)
        except (zipfile.BadZipFile, KeyError, OSError):
            return None
    else:
        try:
            return (rom_dir / source_name).read_bytes()
        except OSError:
            return None


def _overall_status(roms: list[RomScanResult]) -> RomStatus:
    """Determine overall game status from individual ROM results."""
    if not roms:
        return RomStatus.OK
    statuses = {r.status for r in roms}
    if statuses == {RomStatus.OK}:
        return RomStatus.OK
    if statuses == {RomStatus.MISSING}:
        return RomStatus.MISSING
    return RomStatus.BAD_DUMP
