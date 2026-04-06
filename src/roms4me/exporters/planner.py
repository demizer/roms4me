"""Export planner — generates an ExportPlan for a ROM based on analysis results."""

import logging
import zipfile
from pathlib import Path

from roms4me.analyzers.base import Suggestion
from roms4me.exporters.base import ExportPlan
from roms4me.exporters.fixers import ALL_FIXERS, get_system_fixers
from roms4me.handlers.registry import get_rom_extensions
from roms4me.models.dat import DatFile

log = logging.getLogger(__name__)


def plan_export(
    rom_path: Path,
    suggestion: Suggestion,
    dat: DatFile,
    system_name: str = "",
) -> ExportPlan:
    """Generate an export plan for a ROM given an analysis suggestion.

    Runs the base fixers (ALL_FIXERS) followed by any system-specific fixers
    registered in SYSTEM_FIXERS for *system_name* (or *dat.name* when
    *system_name* is omitted).  New system-specific fixers can be added to
    ``exporters/fixers.SYSTEM_FIXERS`` without touching this function.
    """
    plan = ExportPlan(
        rom_file=rom_path.name,
        target_name=f"{suggestion.dat_game_name}.zip",
    )

    # Find the DAT ROM entry for the suggested game
    dat_rom_name = ""
    dat_rom_ext = ""
    for game in dat.games:
        if game.name == suggestion.dat_game_name:
            if game.roms:
                dat_rom_name = game.roms[0].name
                dat_rom_ext = Path(dat_rom_name).suffix.lower()
            break

    # Accepted ROM extensions for this system (used to select primary file from archives)
    accepted_exts: set[str] | None = set(get_rom_extensions(dat.name)) or None

    # Read ROM data (picks primary ROM file from zip using whitelist)
    rom_data = _read_rom_data(rom_path, accepted_exts)
    if not rom_data:
        return plan

    # Run base fixers + any system-specific fixers
    resolve_name = system_name or dat.name
    fixers = ALL_FIXERS + get_system_fixers(resolve_name)
    for fixer in fixers:
        try:
            steps = fixer.suggest(
                rom_path, rom_data,
                suggestion.dat_game_name,
                dat_rom_name, dat_rom_ext,
                accepted_exts,
            )
            plan.steps.extend(steps)
        except Exception as e:
            log.warning("Fixer %s failed for %s: %s", fixer.name, rom_path.name, e)

    return plan


def _read_rom_data(rom_path: Path, accepted_exts: set[str] | None = None) -> bytes | None:
    """Read raw ROM data from a file or the best-matching entry in a zip.

    accepted_exts: whitelist of lowercase extensions (e.g. {'.z64', '.v64'}).
    Falls back to the largest file when no entry matches.
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
                    return zf.read(best.filename)
        else:
            return rom_path.read_bytes()
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("Could not read %s: %s", rom_path, e)
    return None
