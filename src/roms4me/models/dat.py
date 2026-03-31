"""Data models for DAT file contents."""

from pydantic import BaseModel


class RomEntry(BaseModel):
    """A single ROM file within a game."""

    name: str
    size: int
    crc: str = ""
    md5: str = ""
    sha1: str = ""


class GameEntry(BaseModel):
    """A game entry containing one or more ROMs."""

    name: str
    description: str = ""
    roms: list[RomEntry] = []


class DatFile(BaseModel):
    """Parsed DAT file metadata and game entries."""

    name: str
    description: str = ""
    version: str = ""
    author: str = ""
    file_path: str
    games: list[GameEntry] = []
