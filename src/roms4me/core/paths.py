"""Cross-platform path resolution for user data directories."""

import os
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


def get_config_dir() -> Path:
    """Return the platform-appropriate config directory for roms4me."""
    system = platform.system()
    match system:
        case "Linux":
            base = Path.home() / ".config"
        case "Darwin":
            base = Path.home() / "Library" / "Preferences"
        case "Windows":
            base = Path.home() / "AppData" / "Roaming"
        case _:
            base = Path.home()
    return base / "roms4me"


def get_config_path() -> Path:
    """Return the path to the user config file.

    Override with ROMS4ME_CONFIG environment variable for systemd or custom deployments.
    """
    env = os.environ.get("ROMS4ME_CONFIG")
    if env:
        return Path(env)
    return get_config_dir() / "config.toml"


def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    get_data_dir().mkdir(parents=True, exist_ok=True)
    get_dat_dir().mkdir(parents=True, exist_ok=True)
    get_config_dir().mkdir(parents=True, exist_ok=True)
