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


def _inner_ext_from_7z(
    rom_file: Path,
    accepted_exts: set[str] | None = None,
) -> str:
    """Return the extension of the primary ROM entry inside a 7z archive."""
    try:
        import py7zr
        with py7zr.SevenZipFile(rom_file, "r") as szf:
            entries = [e for e in szf.list() if not e.is_directory]
            if accepted_exts:
                candidates = [e for e in entries if Path(e.filename).suffix.lower() in accepted_exts]
                if not candidates:
                    candidates = entries
            else:
                candidates = entries
            if candidates:
                best = max(candidates, key=lambda e: e.uncompressed or 0)
                return Path(best.filename).suffix.lower()
    except Exception:
        pass
    return ""


def _source_rom_ext(rom_file: Path, accepted_exts: set[str] | None = None) -> str:
    """Return the ROM extension from the source file (looking inside archives)."""
    suffix = rom_file.suffix.lower()
    if suffix == ".zip":
        return _inner_ext_from_zip(rom_file, accepted_exts) or ""
    if suffix == ".7z":
        return _inner_ext_from_7z(rom_file, accepted_exts) or ""
    return suffix


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


class LooseFileFixer:
    """Declares that the ROM should be exported as a loose file (no archiving).

    This is the disc-system counterpart to ZipPackageFixer — it explicitly
    sets the output filename to the DAT-correct ROM name, and the executor
    extracts the ROM from any source archive automatically.
    """

    name = "loose_file"

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str,
                accepted_exts: set[str] | None = None) -> list[ExportStep]:
        """Declare the loose output filename.

        Always preserves the source ROM's actual extension — the DAT may list
        a different format (e.g. .bin) than what the user has (.chd, .iso),
        and we don't do format conversion.
        """
        ext = _source_rom_ext(rom_file, accepted_exts) or dat_rom_ext
        target_name = f"{dat_game_name}{ext}"
        return [ExportStep(
            name="loose_file",
            description=f"Export as: {target_name}",
            params={"target_name": target_name},
        )]


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


# ── Fixer instances ────────────────────────────────────────────────────────
_header_strip = HeaderStripFixer()
_rename_ext = RenameExtFixer()
_remove_embedded = RemoveEmbeddedFixer()
_zip_package = ZipPackageFixer()
_loose_file = LooseFileFixer()
_n64_byteorder = N64ByteOrderFixer()

# ── Per-system fixer pipelines ─────────────────────────────────────────────
# Each entry declares the *complete* pipeline for a system.  Systems not
# listed here fall back to _DEFAULT_FIXERS (cartridge-style: includes zip
# packaging).  Disc-based systems explicitly use _DISC_FIXERS (no archiving).
#
# Keys are substrings matched case-insensitively against the DAT system name,
# the same convention as ROM_EXTENSIONS in handlers/registry.py.

_DEFAULT_FIXERS: list = [_header_strip, _rename_ext, _remove_embedded, _zip_package]

_ps2_fixers = [_remove_embedded, _loose_file]
_psp_fixers = [_remove_embedded, _loose_file]
_ps1_fixers = [_loose_file]
_dc_fixers = [_loose_file]
_saturn_fixers = [_loose_file]
_segacd_fixers = [_loose_file]
_n64_fixers = [_header_strip, _rename_ext, _remove_embedded, _zip_package, _n64_byteorder]

SYSTEM_FIXERS: dict[str, list] = {
    # Cartridge overrides
    "Nintendo 64": _n64_fixers,
    "N64": _n64_fixers,
    # Disc-based: single-file images (strip junk, export loose)
    "PlayStation 2": _ps2_fixers,
    "PS2": _ps2_fixers,
    "PlayStation Portable": _psp_fixers,
    "PSP": _psp_fixers,
    # Disc-based: may have companion files (.cue+.bin, .gdi+tracks)
    "PlayStation": _ps1_fixers,
    "PS1": _ps1_fixers,
    "PSX": _ps1_fixers,
    "Dreamcast": _dc_fixers,
    "Saturn": _saturn_fixers,
    "Sega CD": _segacd_fixers,
}


def get_fixers_for_system(system_name: str) -> list:
    """Return the complete fixer pipeline for a system.

    Performs case-insensitive substring matching on *system_name*.  The longest
    matching key wins (so "PlayStation 2" matches before "PlayStation").
    Systems with no match use the default cartridge pipeline.
    """
    lower = system_name.lower()
    for key in sorted(SYSTEM_FIXERS, key=len, reverse=True):
        if key.lower() in lower:
            return SYSTEM_FIXERS[key]
    return _DEFAULT_FIXERS


def system_supports_archiving(system_name: str) -> bool:
    """Return True if the system's fixer pipeline includes ZipPackageFixer."""
    return any(isinstance(f, ZipPackageFixer) for f in get_fixers_for_system(system_name))
