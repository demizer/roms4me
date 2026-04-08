"""Per-system export option definitions.

Each system can declare extra toggle options that appear in the export-settings
dialog.  The registry is keyed by a system-name substring (case-insensitive),
matching the same convention as ``SYSTEM_FIXERS`` in ``fixers.py`` and
``ROM_EXTENSIONS`` in ``handlers/registry.py``.

To add a new option for a system, append an entry here — the UI, API, config
persistence, and executor all pick it up automatically.

The ``compress_7z`` option is added automatically for any system whose fixer
pipeline includes ``ZipPackageFixer`` (i.e. cartridge-based systems).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExportOption:
    """A single boolean toggle shown in the export-settings dialog."""

    id: str
    """Unique key stored in ``ExportSettings.system_options``."""

    label: str
    """Human-readable label rendered next to the checkbox."""

    default: bool = False
    """Default value when the user has never toggled this option."""


_COMPRESS_7Z_OPTION = ExportOption(
    id="compress_7z",
    label="Compress with 7z (smaller files, same ROM data)",
)

# ── Registry ────────────────────────────────────────────────────────────────
# Keyed by system-name substring (case-insensitive match).
# Only system-specific options go here; compress_7z is added automatically
# for systems whose fixer pipeline includes ZipPackageFixer.

_n64_options = [
    ExportOption(
        id="convert_byteorder",
        label="Convert ROM to DAT format (e.g. .v64 → .z64)",
    ),
]

SYSTEM_EXPORT_OPTIONS: dict[str, list[ExportOption]] = {
    "Nintendo 64": _n64_options,
    "N64": _n64_options,
}


def get_system_export_options(system_name: str) -> list[ExportOption]:
    """Return the export options available for *system_name*.

    Automatically prepends ``compress_7z`` for systems whose fixer pipeline
    supports archiving.  Then appends any system-specific options from the
    registry using case-insensitive substring matching.
    """
    from roms4me.exporters.fixers import system_supports_archiving

    result: list[ExportOption] = []
    seen: set[str] = set()

    # Auto-add compress_7z for systems that produce archives
    if system_supports_archiving(system_name):
        result.append(_COMPRESS_7Z_OPTION)
        seen.add(_COMPRESS_7Z_OPTION.id)

    lower = system_name.lower()
    for key, options in SYSTEM_EXPORT_OPTIONS.items():
        if key.lower() in lower:
            for opt in options:
                if opt.id not in seen:
                    result.append(opt)
                    seen.add(opt.id)
    return result
