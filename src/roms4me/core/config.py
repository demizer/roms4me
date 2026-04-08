"""TOML-based configuration for roms4me.

All user settings (theme, paths, saves) are stored in a TOML config file
at the platform-appropriate config directory.
"""

import logging
import threading
import tomllib

import tomli_w
from pydantic import BaseModel

from roms4me.core.paths import get_config_path

log = logging.getLogger(__name__)

_lock = threading.Lock()


class PathEntry(BaseModel):
    """A configured directory path with its associated system name."""

    path: str
    system: str


class ExportSettings(BaseModel):
    """Per-system export preferences."""

    dest: str = ""
    rom_only: bool = True
    one_game_one_rom: bool = True
    region_priority: str = "USA, World, Europe, Japan"
    system_options: dict[str, bool] = {}

    def __init__(self, **data: object) -> None:
        # Migrate legacy convert_byteorder into system_options before validation
        if "convert_byteorder" in data:
            cb = data.pop("convert_byteorder")
            if cb:
                opts = data.setdefault("system_options", {})
                if isinstance(opts, dict) and "convert_byteorder" not in opts:
                    opts["convert_byteorder"] = bool(cb)
        # Migrate legacy archive_format into system_options.compress_7z
        if "archive_format" in data:
            af = data.pop("archive_format")
            if af == "7z":
                opts = data.setdefault("system_options", {})
                if isinstance(opts, dict) and "compress_7z" not in opts:
                    opts["compress_7z"] = True
        super().__init__(**data)


class AppConfig(BaseModel):
    """Application configuration stored in config.toml."""

    theme: str = "auto"  # "light" | "dark" | "auto"
    saves_path: str = ""
    rom_paths: list[PathEntry] = []
    dat_paths: list[PathEntry] = []
    export_settings: dict[str, ExportSettings] = {}


def load_config() -> AppConfig:
    """Load config from TOML file. Creates default if file doesn't exist."""
    path = get_config_path()
    if not path.exists():
        config = AppConfig()
        save_config(config)
        return config
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return AppConfig(**data)
    except Exception as e:
        log.warning("Failed to load config from %s: %s", path, e)
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Save config to TOML file (thread-safe)."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    with _lock:
        with open(path, "wb") as f:
            tomli_w.dump(data, f)


def add_rom_path(path: str, system: str) -> None:
    """Add a ROM path entry to the config."""
    config = load_config()
    entry = PathEntry(path=path, system=system)
    if entry not in config.rom_paths:
        config.rom_paths.append(entry)
        save_config(config)


def remove_rom_path(path: str, system: str) -> None:
    """Remove a ROM path entry from the config."""
    config = load_config()
    entry = PathEntry(path=path, system=system)
    if entry in config.rom_paths:
        config.rom_paths.remove(entry)
        save_config(config)


def add_dat_path(path: str, system: str) -> None:
    """Add a DAT path entry to the config."""
    config = load_config()
    entry = PathEntry(path=path, system=system)
    if entry not in config.dat_paths:
        config.dat_paths.append(entry)
        save_config(config)


def remove_dat_path(path: str, system: str) -> None:
    """Remove a DAT path entry from the config."""
    config = load_config()
    entry = PathEntry(path=path, system=system)
    if entry in config.dat_paths:
        config.dat_paths.remove(entry)
        save_config(config)


def set_theme(theme: str) -> None:
    """Set the theme preference."""
    config = load_config()
    config.theme = theme
    save_config(config)


def set_saves_path(path: str) -> None:
    """Set the saves directory path."""
    config = load_config()
    config.saves_path = path
    save_config(config)


def get_export_settings(system: str) -> ExportSettings:
    """Return export settings for a system, falling back to defaults."""
    return load_config().export_settings.get(system, ExportSettings())


def set_export_settings(system: str, settings: ExportSettings) -> None:
    """Persist export settings for a system."""
    config = load_config()
    config.export_settings[system] = settings
    save_config(config)
