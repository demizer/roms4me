"""Config API routes — theme, saves path, and other settings."""

from fastapi import APIRouter

from roms4me.core.config import (
    ExportSettings,
    get_export_settings,
    load_config,
    set_export_settings,
    set_saves_path,
    set_theme,
)
from roms4me.core.paths import get_config_path

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/path")
async def get_config_file_path() -> dict:
    """Get the config file location."""
    return {"path": str(get_config_path())}


@router.get("/theme")
async def get_theme() -> dict:
    """Get the current theme setting."""
    return {"theme": load_config().theme}


@router.put("/theme")
async def put_theme(req: dict) -> dict:
    """Set the theme (light, dark, or auto)."""
    theme = req.get("theme", "auto")
    if theme not in ("light", "dark", "auto"):
        theme = "auto"
    set_theme(theme)
    return {"theme": theme}


@router.get("/saves-path")
async def get_saves_path() -> dict:
    """Get the configured saves directory path."""
    return {"path": load_config().saves_path}


@router.put("/saves-path")
async def put_saves_path(req: dict) -> dict:
    """Set the saves directory path."""
    path = req.get("path", "")
    set_saves_path(path)
    return {"path": path}


@router.get("/export-settings/{system_name}")
async def get_export_settings_route(system_name: str) -> dict:
    """Get export settings for a system."""
    s = get_export_settings(system_name)
    return s.model_dump()


@router.put("/export-settings/{system_name}")
async def put_export_settings_route(system_name: str, req: dict) -> dict:
    """Save export settings for a system."""
    archive_format = req.get("archive_format", "zip")
    if archive_format not in ("zip", "7z"):
        archive_format = "zip"
    s = ExportSettings(
        dest=req.get("dest", ""),
        rom_only=bool(req.get("rom_only", True)),
        one_game_one_rom=bool(req.get("one_game_one_rom", True)),
        archive_format=archive_format,
        region_priority=req.get("region_priority", "USA, World, Europe, Japan"),
        convert_byteorder=bool(req.get("convert_byteorder", False)),
    )
    set_export_settings(system_name, s)
    return s.model_dump()
