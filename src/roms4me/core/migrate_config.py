"""Migrate ROM/DAT paths from SQLite DB to TOML config file.

Run once on startup — if config.toml doesn't exist but the DB has path entries,
copy them over. Does not delete DB rows (that happens via Alembic later).
"""

import logging

from sqlmodel import select

from roms4me.core.config import AppConfig, PathEntry, save_config
from roms4me.core.database import get_session
from roms4me.core.paths import get_config_path, get_data_dir
from roms4me.models.db import DatPath, RomPath, System

log = logging.getLogger(__name__)

_MIGRATION_MARKER = ".config_migrated"


def migrate_db_to_toml() -> None:
    """Migrate path config from DB to TOML if needed (runs once)."""
    marker = get_data_dir() / _MIGRATION_MARKER
    if marker.exists():
        return

    with get_session() as session:
        systems = {s.id: s.name for s in session.exec(select(System)).all()}
        dat_paths = session.exec(select(DatPath)).all()
        rom_paths = session.exec(select(RomPath)).all()

        if dat_paths or rom_paths:
            config = AppConfig(
                dat_paths=[
                    PathEntry(path=dp.path, system=systems.get(dp.system_id, ""))
                    for dp in dat_paths
                ],
                rom_paths=[
                    PathEntry(path=rp.path, system=systems.get(rp.system_id, ""))
                    for rp in rom_paths
                ],
            )
            save_config(config)
            log.info(
                "Migrated %d DAT paths and %d ROM paths from DB to %s",
                len(dat_paths),
                len(rom_paths),
                get_config_path(),
            )

    # Mark migration as done so it never re-runs
    marker.touch()
