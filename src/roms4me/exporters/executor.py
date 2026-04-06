"""Export executor — applies an ExportPlan to produce a destination ROM file."""

import shutil
import zipfile
from pathlib import Path

from roms4me.exporters.base import ExportPlan


def execute_export(rom_path: Path, plan: ExportPlan, dest_dir: Path) -> Path:
    """Apply an ExportPlan and write the result to dest_dir.

    Returns the path to the exported file. Overwrites any existing file.
    Creates dest_dir (and any parents) if it does not exist.

    Works on Linux, macOS, and Windows via pathlib.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not plan.steps:
        # No transformations needed — copy file as-is using the target name
        out_path = dest_dir / plan.target_name
        shutil.copy2(str(rom_path), str(out_path))
        return out_path

    rom_data = _read_rom_data(rom_path)
    if rom_data is None:
        raise OSError(f"Could not read ROM data from {rom_path}")

    zip_name: str | None = None
    inner_name: str | None = None

    for step in plan.steps:
        if step.name == "strip_header":
            header_size = step.params["header_size"]
            rom_data = rom_data[header_size:]
        elif step.name == "zip_package":
            zip_name = step.params["zip_name"]
            inner_name = step.params["inner_name"]
        # rename_ext is handled implicitly: inner_name already has the correct extension

    if zip_name:
        out_path = dest_dir / zip_name
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(inner_name or plan.target_name, rom_data)
    else:
        out_path = dest_dir / plan.target_name
        out_path.write_bytes(rom_data)

    return out_path


def _read_rom_data(rom_path: Path) -> bytes | None:
    """Read ROM data from a loose file or the first entry in a zip."""
    try:
        if rom_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(rom_path, "r") as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        return zf.read(info.filename)
        else:
            return rom_path.read_bytes()
    except (zipfile.BadZipFile, OSError):
        return None
    return None
