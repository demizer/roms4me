"""Per-system export option definitions.

Each system can declare extra toggle options that appear in the export-settings
dialog.  The registry is keyed by a system-name substring (case-insensitive),
matching the same convention as ``SYSTEM_FIXERS`` in ``fixers.py`` and
``ROM_EXTENSIONS`` in ``handlers/registry.py``.

To add a new option for a system, append an entry here — the UI, API, config
persistence, and executor all pick it up automatically.
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


# ── Registry ────────────────────────────────────────────────────────────────
# Keyed by system-name substring (case-insensitive match).

SYSTEM_EXPORT_OPTIONS: dict[str, list[ExportOption]] = {
    "Nintendo 64": [
        ExportOption(
            id="convert_byteorder",
            label="Convert ROM to DAT format (e.g. .v64 → .z64)",
        ),
    ],
    "PlayStation 2": [
        ExportOption(
            id="extract_disc_image",
            label="Extract disc images from archives (ISO, CHD, etc.)",
        ),
    ],
    "PlayStation Portable": [
        ExportOption(
            id="extract_disc_image",
            label="Extract disc images from archives (ISO, CSO, etc.)",
        ),
    ],
    "Dreamcast": [
        ExportOption(
            id="extract_disc_image",
            label="Extract disc images from archives (CHD, GDI, etc.)",
        ),
    ],
    "Saturn": [
        ExportOption(
            id="extract_disc_image",
            label="Extract disc images from archives (CHD, BIN, etc.)",
        ),
    ],
    "Sega CD": [
        ExportOption(
            id="extract_disc_image",
            label="Extract disc images from archives (CHD, BIN, etc.)",
        ),
    ],
    "PlayStation": [
        ExportOption(
            id="extract_disc_image",
            label="Extract disc images from archives (CHD, BIN, etc.)",
        ),
    ],
}


def get_system_export_options(system_name: str) -> list[ExportOption]:
    """Return the extra export options available for *system_name*.

    Uses case-insensitive substring matching, merging all matching entries.
    """
    result: list[ExportOption] = []
    seen: set[str] = set()
    lower = system_name.lower()
    for key, options in SYSTEM_EXPORT_OPTIONS.items():
        if key.lower() in lower:
            for opt in options:
                if opt.id not in seen:
                    result.append(opt)
                    seen.add(opt.id)
    return result
