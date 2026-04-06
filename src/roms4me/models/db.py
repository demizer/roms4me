"""SQLModel database models."""

from datetime import datetime

from sqlmodel import Field, SQLModel


class System(SQLModel, table=True):
    """A game system/platform (e.g., MAME, SNES, Genesis)."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)


class DatPath(SQLModel, table=True):
    """A user-configured directory containing DAT files."""

    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(index=True)
    system_id: int = Field(foreign_key="system.id", index=True)


class RomPath(SQLModel, table=True):
    """A user-configured directory containing ROM files."""

    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(index=True)
    system_id: int = Field(foreign_key="system.id", index=True)


class ScanResult(SQLModel, table=True):
    """Result of scanning a single game against a DAT entry."""

    id: int | None = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="system.id", index=True)
    game_name: str = Field(index=True)
    description: str = ""
    file_name: str = ""
    rom_type: str = ""
    expected_file_name: str = ""
    status: str = ""  # ok, missing, bad_dump, checksum_mismatch, size_mismatch, unmatched, matched
    note: str = ""  # explanation for unmatched items
    plan: str = ""  # export plan summary (e.g., "modify", "rename", "ok")


class PrescanInfo(SQLModel, table=True):
    """Pre-scan compatibility result for a system."""

    id: int | None = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="system.id", index=True)
    rating: str = ""  # green, yellow, red
    reason: str = ""
    dat_game_count: int = 0
    dat_extensions: str = ""  # comma-separated
    rom_file_count: int = 0
    rom_extensions: str = ""  # comma-separated
    name_matches: int = 0


class ScanMeta(SQLModel, table=True):
    """Metadata about the last scan/prescan."""

    id: int | None = Field(default=None, primary_key=True)
    last_scan: datetime | None = Field(default=None)
    log: str = ""
