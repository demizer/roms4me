"""Built-in export fixers — detect and suggest ROM transformations."""

import logging
from pathlib import Path

from roms4me.exporters.base import ExportStep

log = logging.getLogger(__name__)

# Known copier header sizes by extension
HEADER_EXTENSIONS = {
    ".smc": 512,   # SNES Super Magicom
    ".swc": 512,   # SNES Super Wild Card
    ".fig": 512,   # SNES Pro Fighter
    ".nes": 16,    # NES iNES header (when DAT expects headerless)
}


class HeaderStripFixer:
    """Suggests stripping copier headers when detected."""

    name = "strip_header"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str) -> list[ExportStep]:
        """Detect copier headers and suggest stripping."""
        # Get the inner filename extension (from zip or loose)
        inner_ext = Path(rom_file.stem).suffix.lower() if rom_file.suffix.lower() == ".zip" else rom_file.suffix.lower()
        # For zips, we need to check the inner file extension
        if rom_file.suffix.lower() == ".zip":
            import zipfile
            try:
                with zipfile.ZipFile(rom_file) as zf:
                    for info in zf.infolist():
                        if not info.is_dir():
                            inner_ext = Path(info.filename).suffix.lower()
                            break
            except Exception:
                pass

        header_size = HEADER_EXTENSIONS.get(inner_ext)
        if not header_size:
            return []

        # Check if data size - header = a round ROM size
        if len(rom_data) <= header_size:
            return []

        stripped_size = len(rom_data) - header_size
        # ROM sizes are typically powers of 2 or multiples of common sizes
        if stripped_size % 1024 != 0:
            return []

        # Check header is mostly zeros (characteristic of copier headers)
        header = rom_data[:header_size]
        zero_pct = sum(1 for b in header if b == 0) * 100 // header_size
        if zero_pct < 80:
            return []

        return [ExportStep(
            name="strip_header",
            description=f"Strip {header_size}-byte copier header ({inner_ext} format, {zero_pct}% zeros)",
            params={"header_size": header_size, "source_ext": inner_ext},
        )]


class RenameExtFixer:
    """Suggests renaming the ROM extension to match the DAT."""

    name = "rename_ext"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str) -> list[ExportStep]:
        """Suggest extension rename if current doesn't match DAT."""
        if not dat_rom_ext:
            return []

        # Get actual inner extension
        inner_ext = rom_file.suffix.lower()
        if rom_file.suffix.lower() == ".zip":
            import zipfile
            try:
                with zipfile.ZipFile(rom_file) as zf:
                    for info in zf.infolist():
                        if not info.is_dir():
                            inner_ext = Path(info.filename).suffix.lower()
                            break
            except Exception:
                pass

        if inner_ext == dat_rom_ext.lower():
            return []

        return [ExportStep(
            name="rename_ext",
            description=f"Rename extension: {inner_ext} → {dat_rom_ext}",
            params={"from_ext": inner_ext, "to_ext": dat_rom_ext},
        )]


class ZipPackageFixer:
    """Suggests zipping the ROM with the DAT-correct filename."""

    name = "zip_package"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str) -> list[ExportStep]:
        """Suggest packaging as a zip with the correct DAT name."""
        target_zip = f"{dat_game_name}.zip"
        target_inner = dat_rom_name

        return [ExportStep(
            name="zip_package",
            description=f"Package as: {target_zip} containing {target_inner}",
            params={
                "zip_name": target_zip,
                "inner_name": target_inner,
            },
        )]


# All fixers in pipeline order
ALL_FIXERS = [
    HeaderStripFixer(),
    RenameExtFixer(),
    ZipPackageFixer(),
]
