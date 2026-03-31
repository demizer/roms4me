"""Export planner — generates an ExportPlan for a ROM based on analysis results."""

import logging
import zipfile
from pathlib import Path

from roms4me.analyzers.base import Suggestion
from roms4me.exporters.base import ExportPlan
from roms4me.exporters.fixers import ALL_FIXERS
from roms4me.models.dat import DatFile

log = logging.getLogger(__name__)


def plan_export(
    rom_path: Path,
    suggestion: Suggestion,
    dat: DatFile,
) -> ExportPlan:
    """Generate an export plan for a ROM given an analysis suggestion.

    Runs all fixers to determine what transformations are needed
    to produce a DAT-correct ROM.
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

    # Read ROM data
    rom_data = _read_rom_data(rom_path)
    if not rom_data:
        return plan

    # Run all fixers
    for fixer in ALL_FIXERS:
        try:
            steps = fixer.suggest(
                rom_path, rom_data,
                suggestion.dat_game_name,
                dat_rom_name, dat_rom_ext,
            )
            plan.steps.extend(steps)
        except Exception as e:
            log.warning("Fixer %s failed for %s: %s", fixer.name, rom_path.name, e)

    return plan


def _read_rom_data(rom_path: Path) -> bytes | None:
    """Read raw ROM data from a file or the first entry in a zip."""
    try:
        if rom_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(rom_path, "r") as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        return zf.read(info.filename)
        else:
            return rom_path.read_bytes()
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("Could not read %s: %s", rom_path, e)
    return None
