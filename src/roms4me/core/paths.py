"""Cross-platform path resolution for user data directories."""

import platform
from pathlib import Path


def get_data_dir() -> Path:
    """Return the platform-appropriate user data directory for roms4me."""
    system = platform.system()
    match system:
        case "Linux":
            base = Path.home() / ".local" / "share"
        case "Darwin":
            base = Path.home() / "Library" / "Application Support"
        case "Windows":
            appdata = Path.home() / "AppData" / "Roaming"
            base = appdata
        case _:
            base = Path.home()
    return base / "roms4me"


def get_dat_dir() -> Path:
    """Return the default directory for DAT files."""
    return get_data_dir() / "dats"


def get_config_path() -> Path:
    """Return the path to the user config file."""
    return get_data_dir() / "config.json"


def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    get_data_dir().mkdir(parents=True, exist_ok=True)
    get_dat_dir().mkdir(parents=True, exist_ok=True)
