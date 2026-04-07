"""Export executor — applies an ExportPlan to produce a destination ROM file."""

import io
import shutil
import zipfile
from pathlib import Path

from roms4me.exporters.base import ExportPlan


_DISC_IMAGE_EXTS = frozenset({
    ".iso", ".chd", ".bin", ".cue", ".img",
    ".cso", ".zso", ".gz", ".gdi", ".cdi",
})


def execute_export(rom_path: Path, plan: ExportPlan, dest_dir: Path,
                   archive_format: str = "zip",
                   rom_only: bool = True,
                   convert_byteorder: bool = False,
                   extract_disc_image: bool = False) -> Path:
    """Apply an ExportPlan and write the result to dest_dir.

    archive_format: "zip" (default) or "7z".
    rom_only: when True (default) the output archive contains only the primary
              ROM file.  When False, all files from the source zip are preserved
              alongside the processed ROM.
    extract_disc_image: when True, disc images (ISO, CHD, BIN, etc.) are
              extracted from archives as loose files instead of being re-archived.

    Returns the path to the exported file. Overwrites any existing file.
    Creates dest_dir (and any parents) if it does not exist.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not plan.steps:
        # No transformations needed.
        # When extract_disc_image is on and the source is an archive
        # containing a disc image, extract it as a loose file.
        if extract_disc_image and rom_path.suffix.lower() in {".zip", ".7z"}:
            inner_ext = _get_inner_ext(rom_path)
            if inner_ext and inner_ext in _DISC_IMAGE_EXTS:
                rom_data = _read_rom_data(rom_path)
                if rom_data is not None:
                    stem = Path(plan.target_name).stem
                    out_path = dest_dir / (stem + inner_ext)
                    out_path.write_bytes(rom_data)
                    return out_path
        out_path = dest_dir / plan.target_name
        shutil.copy2(str(rom_path), str(out_path))
        return out_path

    # Determine the preferred inner extension from the compress_package step so
    # _read_rom_data picks the correct file (not a bundled readme or nfo).
    preferred_ext = ""
    for step in plan.steps:
        if step.name == "compress_package":
            preferred_ext = Path(step.params.get("inner_name", "")).suffix.lower()
            break

    # If byte-order conversion is enabled, override preferred_ext with the source
    # format's extension so the correct ROM entry is extracted from the archive.
    if convert_byteorder:
        for step in plan.steps:
            if step.name == "convert_byteorder":
                from roms4me.exporters.fixers import _N64_FMT_TO_EXT
                from_fmt = step.params.get("from_fmt", "")
                if from_fmt in _N64_FMT_TO_EXT:
                    preferred_ext = _N64_FMT_TO_EXT[from_fmt]
                break

    rom_data = _read_rom_data(rom_path, preferred_ext)
    if rom_data is None:
        raise OSError(f"Could not read ROM data from {rom_path}")

    zip_name: str | None = None
    inner_name: str | None = None

    converted_ext: str | None = None  # set by convert_byteorder step; updates inner_name

    for step in plan.steps:
        if step.name == "strip_header":
            header_size = step.params["header_size"]
            rom_data = rom_data[header_size:]
        elif step.name == "convert_byteorder":
            if convert_byteorder:
                from roms4me.analyzers.n64_byteorder import to_bigendian
                from_fmt = step.params.get("from_fmt", "bigendian")
                to_fmt = step.params.get("to_fmt", "bigendian")
                # Normalise to BigEndian, then apply the target encoding
                # (to_bigendian is self-inverse for both swap operations)
                be = to_bigendian(rom_data, from_fmt)
                rom_data = to_bigendian(be, to_fmt)
                converted_ext = step.params.get("new_ext", "")
        elif step.name == "compress_package":
            zip_name = step.params["zip_name"]
            inner_name = step.params["inner_name"]
            # Update the inner filename extension when byte-order conversion ran
            if converted_ext:
                stem = Path(inner_name).stem
                inner_name = stem + converted_ext
        # rename_ext handled implicitly: inner_name already carries the correct extension
        # remove_embedded handled implicitly when rom_only=True (clean archive from scratch)

    # When extract_disc_image is on and the inner file is a disc image,
    # write it as a loose file rather than wrapping it in a zip/7z.
    if extract_disc_image and zip_name and inner_name:
        inner_ext = Path(inner_name).suffix.lower()
        if inner_ext in _DISC_IMAGE_EXTS:
            out_path = dest_dir / inner_name
            out_path.write_bytes(rom_data)
            return out_path

    if zip_name:
        final_inner = inner_name or plan.target_name
        # Collect extra files from source zip when rom_only=False
        extras: list[tuple[str, bytes]] = []
        if not rom_only and rom_path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(rom_path, "r") as src_zf:
                    for entry in src_zf.infolist():
                        if entry.is_dir():
                            continue
                        entry_ext = Path(entry.filename).suffix.lower()
                        if entry_ext == preferred_ext:
                            continue  # primary ROM — already processed above
                        extras.append((entry.filename, src_zf.read(entry.filename)))
            except (zipfile.BadZipFile, OSError):
                pass

        if archive_format == "7z":
            import py7zr
            out_path = dest_dir / Path(zip_name).with_suffix(".7z").name
            payload = {final_inner: io.BytesIO(rom_data)}
            for name, data in extras:
                payload[name] = io.BytesIO(data)
            with py7zr.SevenZipFile(out_path, "w") as szf:
                for name, data in payload.items():
                    szf.writef(data, name)
        else:
            out_path = dest_dir / zip_name
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(final_inner, rom_data)
                for name, data in extras:
                    zf.writestr(name, data)
    else:
        out_path = dest_dir / plan.target_name
        out_path.write_bytes(rom_data)

    return out_path


def _get_inner_ext(archive_path: Path) -> str:
    """Return the extension of the largest file inside a zip/7z archive."""
    suffix = archive_path.suffix.lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                entries = [e for e in zf.infolist() if not e.is_dir()]
                if entries:
                    best = max(entries, key=lambda e: e.file_size)
                    return Path(best.filename).suffix.lower()
        elif suffix == ".7z":
            import py7zr
            with py7zr.SevenZipFile(archive_path, "r") as szf:
                entries = [e for e in szf.list() if not e.is_directory]
                if entries:
                    best = max(entries, key=lambda e: e.uncompressed or 0)
                    return Path(best.filename).suffix.lower()
    except Exception:
        pass
    return ""


def _read_rom_data(rom_path: Path, preferred_ext: str = "") -> bytes | None:
    """Read ROM data from a loose file or the best-matching entry in a zip/7z.

    preferred_ext: if set (e.g. '.z64'), prefer entries with that extension.
    Falls back to the largest file when nothing matches.
    """
    try:
        suffix = rom_path.suffix.lower()
        if suffix == ".zip":
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
        elif suffix == ".7z":
            import py7zr
            with py7zr.SevenZipFile(rom_path, "r") as szf:
                entries = [e for e in szf.list() if not e.is_directory]
                if preferred_ext:
                    candidates = [e for e in entries if Path(e.filename).suffix.lower() == preferred_ext]
                    if not candidates:
                        candidates = entries
                else:
                    candidates = entries
                if candidates:
                    best = max(candidates, key=lambda e: e.uncompressed or 0)
                    data = szf.read([best.filename])
                    if data and best.filename in data:
                        return data[best.filename].read()
        else:
            return rom_path.read_bytes()
    except (zipfile.BadZipFile, OSError):
        return None
    return None
