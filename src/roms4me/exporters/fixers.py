"""Built-in export fixers — detect and suggest ROM transformations."""

import logging
import zipfile
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

# N64 byte-order variant extensions — all three hold identical data, just
# arranged differently.  We never rename between them on export because the
# game is playable as-is; only the CRC normalisation step (in the analyzer)
# needs the conversion.
_N64_EXTS: frozenset[str] = frozenset({".z64", ".v64", ".n64"})

# Map N64 file extension → canonical byte-order format name
_N64_EXT_TO_FMT: dict[str, str] = {
    ".z64": "bigendian",
    ".v64": "byteswapped",
    ".n64": "littleendian",
}

# Map byte-order format name → canonical extension
_N64_FMT_TO_EXT: dict[str, str] = {v: k for k, v in _N64_EXT_TO_FMT.items()}


def _inner_ext_from_zip(
    rom_file: Path,
    accepted_exts: set[str] | None = None,
) -> str:
    """Return the extension of the primary ROM entry inside a zip.

    Uses accepted_exts whitelist to prefer ROM files; falls back to the
    largest file when nothing matches.  Returns empty string on failure.
    """
    try:
        with zipfile.ZipFile(rom_file) as zf:
            entries = [e for e in zf.infolist() if not e.is_dir()]
            if accepted_exts:
                candidates = [e for e in entries if Path(e.filename).suffix.lower() in accepted_exts]
                if not candidates:
                    candidates = entries
            else:
                candidates = entries
            if candidates:
                best = max(candidates, key=lambda e: e.file_size)
                return Path(best.filename).suffix.lower()
    except Exception:
        pass
    return ""


class HeaderStripFixer:
    """Suggests stripping copier headers when detected."""

    name = "strip_header"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str,
                accepted_exts: set[str] | None = None) -> list[ExportStep]:
        """Detect copier headers and suggest stripping."""
        if rom_file.suffix.lower() == ".zip":
            inner_ext = _inner_ext_from_zip(rom_file, accepted_exts)
        else:
            inner_ext = rom_file.suffix.lower()

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
    """Suggests renaming the ROM extension to match the DAT.

    N64 byte-order variants (.z64/.v64/.n64) are never renamed — they hold
    identical data and the game is playable in any of the three formats.
    """

    name = "rename_ext"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str,
                accepted_exts: set[str] | None = None) -> list[ExportStep]:
        """Suggest extension rename if current doesn't match DAT."""
        if not dat_rom_ext:
            return []

        if rom_file.suffix.lower() == ".zip":
            inner_ext = _inner_ext_from_zip(rom_file, accepted_exts)
        else:
            inner_ext = rom_file.suffix.lower()

        if not inner_ext or inner_ext == dat_rom_ext.lower():
            return []

        # N64 byte-order variants are equivalent — no rename needed
        if inner_ext in _N64_EXTS and dat_rom_ext.lower() in _N64_EXTS:
            return []

        return [ExportStep(
            name="rename_ext",
            description=f"Rename extension: {inner_ext} → {dat_rom_ext}",
            params={"from_ext": inner_ext, "to_ext": dat_rom_ext},
        )]


class RemoveEmbeddedFixer:
    """Suggests removing non-ROM files from a zip archive."""

    name = "remove_embedded"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str,
                accepted_exts: set[str] | None = None) -> list[ExportStep]:
        """Suggest removing files whose extension is not in accepted_exts."""
        if rom_file.suffix.lower() != ".zip":
            return []
        if not accepted_exts:
            return []

        steps = []
        try:
            with zipfile.ZipFile(rom_file) as zf:
                for entry in zf.infolist():
                    if entry.is_dir():
                        continue
                    ext = Path(entry.filename).suffix.lower()
                    if ext not in accepted_exts:
                        steps.append(ExportStep(
                            name="remove_embedded",
                            description=f"Remove non-essential embedded file: {entry.filename}",
                            params={"filename": entry.filename},
                        ))
        except Exception:
            pass
        return steps


class ZipPackageFixer:
    """Suggests zipping the ROM with the DAT-correct filename.

    For N64 byte-order variants the inner filename keeps the original
    extension rather than the DAT extension (.z64), since the bytes are
    not being converted.
    """

    name = "compress_package"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str,
                accepted_exts: set[str] | None = None) -> list[ExportStep]:
        """Suggest packaging as a zip with the correct DAT name."""
        target_zip = f"{dat_game_name}.zip"

        # For N64 variants: preserve the actual ROM extension in the inner name
        # so we don't misrepresent the byte order of the exported file.
        if rom_file.suffix.lower() == ".zip":
            inner_ext = _inner_ext_from_zip(rom_file, accepted_exts)
        else:
            inner_ext = rom_file.suffix.lower()

        if inner_ext in _N64_EXTS and dat_rom_ext.lower() in _N64_EXTS:
            target_inner = f"{dat_game_name}{inner_ext}"
        else:
            target_inner = dat_rom_name

        return [ExportStep(
            name="compress_package",
            description=f"Package as: {target_zip} containing {target_inner}",
            params={
                "zip_name": target_zip,
                "inner_name": target_inner,
            },
        )]


# All fixers in pipeline order — run for every system
ALL_FIXERS = [
    HeaderStripFixer(),
    RenameExtFixer(),
    RemoveEmbeddedFixer(),
    ZipPackageFixer(),
]

class N64ByteOrderFixer:
    """Suggests a byte-order conversion step when the ROM format differs from the DAT.

    Only suggests when the detected format (via magic bytes) disagrees with the
    format the DAT entry expects (determined from the DAT ROM extension).
    The step is advisory — the executor applies it only when the user has opted
    in via the ``convert_byteorder`` export setting.
    """

    name = "convert_byteorder"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str,
                accepted_exts: set[str] | None = None) -> list[ExportStep]:
        """Suggest byte-order conversion when ROM format ≠ DAT expected format."""
        from roms4me.analyzers.n64_byteorder import _FORMAT_LABEL, detect_n64_format

        if rom_file.suffix.lower() == ".zip":
            inner_ext = _inner_ext_from_zip(rom_file, accepted_exts)
        else:
            inner_ext = rom_file.suffix.lower()

        # Only applicable if both current and expected extensions are N64 variants
        if inner_ext not in _N64_EXTS or dat_rom_ext.lower() not in _N64_EXTS:
            return []

        # Detect actual byte order from magic bytes
        current_fmt = detect_n64_format(rom_data) or _N64_EXT_TO_FMT.get(inner_ext, "")
        target_fmt = _N64_EXT_TO_FMT.get(dat_rom_ext.lower(), "")

        if not current_fmt or not target_fmt or current_fmt == target_fmt:
            return []

        current_label = _FORMAT_LABEL.get(current_fmt, current_fmt)
        target_label = _FORMAT_LABEL.get(target_fmt, target_fmt)
        new_ext = _N64_FMT_TO_EXT.get(target_fmt, dat_rom_ext.lower())

        return [ExportStep(
            name="convert_byteorder",
            description=f"Convert byte order: {current_label} → {target_label}",
            params={
                "from_fmt": current_fmt,
                "to_fmt": target_fmt,
                "new_ext": new_ext,
            },
        )]


# System-specific fixers — keyed by a substring that must appear in the DAT
# system name (case-insensitive), same matching convention as ROM_EXTENSIONS in
# handlers/registry.py.  Add new entries here to extend the export pipeline for
# a system without touching the base fixers.
SYSTEM_FIXERS: dict[str, list] = {
    "Nintendo 64": [N64ByteOrderFixer()],
}


def get_system_fixers(dat_name: str) -> list:
    """Return extra fixers for a system, or [] if none are registered.

    Performs substring matching on *dat_name* (case-insensitive), identical to
    how :func:`roms4me.handlers.registry.get_rom_extensions` resolves systems.
    All matching entries are merged in the order they appear in the registry.
    """
    result = []
    lower = dat_name.lower()
    for key, fixers in SYSTEM_FIXERS.items():
        if key.lower() in lower:
            result.extend(fixers)
    return result
