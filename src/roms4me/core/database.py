"""Database engine and session management."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlmodel import Session, create_engine

from roms4me.core.paths import get_data_dir

_engine = None


def _alembic_config() -> Config:
    """Build an Alembic Config pointing at our migrations."""
    ini_path = Path(__file__).parents[3] / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option(
        "script_location", str(Path(__file__).parent.parent / "migrations")
    )
    return cfg


def get_engine():
    """Get or create the SQLite engine."""
    global _engine
    if _engine is None:
        db_path = get_data_dir() / "roms4me.db"
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return _engine


def run_migrations() -> None:
    """Run alembic migrations to head."""
    cfg = _alembic_config()
    db_path = get_data_dir() / "roms4me.db"
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def get_session() -> Session:
    """Create a new database session."""
    return Session(get_engine())
