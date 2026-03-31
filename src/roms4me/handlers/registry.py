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
