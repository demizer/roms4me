"""Handler registry — maps system names to their handler instances."""

import logging

from roms4me.handlers.base import SystemHandler
from roms4me.handlers.default import DefaultHandler

log = logging.getLogger(__name__)

# Default handler for most systems
_default = DefaultHandler()

# System name pattern -> handler instance
# Add custom handlers here as they're built, e.g.:
#   "MAME": ArcadeHandler(),
#   "Neo Geo": ArcadeHandler(),
_HANDLERS: dict[str, SystemHandler] = {}

# Supported ROM file extensions per system (substring match on system name).
# Order matters: preferred/canonical format first.
# Used to identify the primary ROM file inside a zip archive.
ROM_EXTENSIONS: dict[str, list[str]] = {
    "Nintendo 64": [".z64", ".v64", ".n64"],
    "Super Nintendo": [".sfc", ".smc", ".swc", ".fig"],
    "Nintendo Entertainment System": [".nes", ".unf", ".unif"],
    "Famicom Disk System": [".fds"],
    "Game Boy Advance": [".gba"],
    "Game Boy Color": [".gbc"],
    "Game Boy": [".gb"],
    "Nintendo DS": [".nds"],
    "Nintendo 3DS": [".3ds", ".cia"],
    "Mega Drive": [".md", ".smd", ".bin", ".gen"],
    "Genesis": [".md", ".smd", ".bin", ".gen"],
    "Master System": [".sms"],
    "Game Gear": [".gg"],
    "Saturn": [".bin", ".iso", ".img", ".chd", ".cue"],
    "Dreamcast": [".bin", ".iso", ".chd", ".cdi", ".gdi"],
    "PlayStation": [".bin", ".iso", ".img", ".chd", ".cue"],
    "PlayStation 2": [".iso", ".bin", ".chd"],
    "PlayStation Portable": [".iso", ".cso", ".chd"],
    "PC Engine": [".pce", ".bin"],
    "TurboGrafx": [".pce", ".bin"],
    "Neo Geo": [".neo"],
    "Neo Geo Pocket": [".ngp", ".ngc"],
    "WonderSwan": [".ws", ".wsc"],
    "Atari 2600": [".a26", ".bin"],
    "Atari 5200": [".a52", ".bin"],
    "Atari 7800": [".a78", ".bin"],
    "Atari Lynx": [".lnx"],
    "Atari Jaguar": [".j64", ".jag", ".bin"],
    "32X": [".32x", ".bin"],
    "Sega CD": [".bin", ".iso", ".chd"],
    "Virtual Boy": [".vb"],
}


def get_handler(system_name: str) -> SystemHandler:
    """Get the handler for a system. Falls back to default."""
    # Check exact match first
    if system_name in _HANDLERS:
        return _HANDLERS[system_name]

    # Check if any key is a substring of the system name
    for key, handler in _HANDLERS.items():
        if key.lower() in system_name.lower():
            return handler

    return _default


def get_rom_extensions(system_name: str) -> list[str]:
    """Return supported ROM file extensions for a system (lowercase, with dot).

    Returns an empty list if the system is not in the registry.
    The first extension is the canonical/preferred format.
    """
    for key, exts in ROM_EXTENSIONS.items():
        if key.lower() in system_name.lower():
            return exts
    return []
