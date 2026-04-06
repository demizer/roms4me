"""Export executor — applies an ExportPlan to produce a destination ROM file."""

import io
import shutil
import zipfile
from pathlib import Path

from roms4me.exporters.base import ExportPlan


def execute_export(rom_path: Path, plan: ExportPlan, dest_dir: Path,
                   archive_format: str = "zip") -> Path:
    """Apply an ExportPlan and write the result to dest_dir.

    archive_format: "zip" (default) or "7z".

    Returns the path to the exported file. Overwrites any existing file.
    Creates dest_dir (and any parents) if it does not exist.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not plan.steps:
        # No transformations needed — copy file as-is using the target name
        out_path = dest_dir / plan.target_name
        shutil.copy2(str(rom_path), str(out_path))
        return out_path

    # Determine the preferred inner extension from the zip_package step so
    # _read_rom_data picks the correct file (not a bundled readme or nfo).
    preferred_ext = ""
    for step in plan.steps:
        if step.name == "zip_package":
            preferred_ext = Path(step.params.get("inner_name", "")).suffix.lower()
            break

    rom_data = _read_rom_data(rom_path, preferred_ext)
    if rom_data is None:
        raise OSError(f"Could not read ROM data from {rom_path}")

    zip_name: str | None = None
    inner_name: str | None = None

    for step in plan.steps:
        if step.name == "strip_header":
            header_size = step.params["header_size"]
            rom_data = rom_data[header_size:]
        elif step.name == "convert_byteorder":
            from roms4me.analyzers.n64_byteorder import to_bigendian
            rom_data = to_bigendian(rom_data, step.params.get("from_fmt", "byteswapped"))
        elif step.name == "zip_package":
            zip_name = step.params["zip_name"]
            inner_name = step.params["inner_name"]
        # rename_ext handled implicitly: inner_name already carries the correct extension
        # remove_embedded handled implicitly: executor builds a clean archive from scratch

    if zip_name:
        final_inner = inner_name or plan.target_name
        if archive_format == "7z":
            import py7zr
            out_path = dest_dir / Path(zip_name).with_suffix(".7z").name
            with py7zr.SevenZipFile(out_path, "w") as szf:
                szf.write({final_inner: io.BytesIO(rom_data)})
        else:
            out_path = dest_dir / zip_name
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(final_inner, rom_data)
    else:
        out_path = dest_dir / plan.target_name
        out_path.write_bytes(rom_data)

    return out_path


def _read_rom_data(rom_path: Path, preferred_ext: str = "") -> bytes | None:
    """Read ROM data from a loose file or the best-matching entry in a zip.

    preferred_ext: if set (e.g. '.z64'), prefer entries with that extension.
    Falls back to the largest file when nothing matches.
    """
    try:
        if rom_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(rom_path, "r") as zf:
                entries = [e for e in zf.infolist() if not e.is_dir()]
                if preferred_ext:
                    candidates = [e for e in entries if Path(e.filename).suffix.lower() == preferred_ext]
                    if not candidates:
                        candidates = entries
                else:
                    candidates = entries
                if candidates:
                    best = max(candidates, key=lambda e: e.file_size)
                    return zf.read(best.filename)
        else:
            return rom_path.read_bytes()
    except (zipfile.BadZipFile, OSError):
        return None
    return None
