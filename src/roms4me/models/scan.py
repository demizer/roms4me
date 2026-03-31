"""Data models for ROM scan results."""

from enum import StrEnum

from pydantic import BaseModel


class RomStatus(StrEnum):
    """Status of a ROM file after verification."""

    OK = "ok"
    MISSING = "missing"
    BAD_DUMP = "bad_dump"
    NOT_NEEDED = "not_needed"
    SIZE_MISMATCH = "size_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"


class RomScanResult(BaseModel):
    """Result of scanning a single ROM file."""

    name: str
    expected_name: str
    status: RomStatus
    size: int = 0
    expected_size: int = 0


class GameScanResult(BaseModel):
    """Result of scanning all ROMs for a game."""

    name: str
    description: str = ""
    file_name: str = ""
    expected_file_name: str = ""
    status: RomStatus
    roms: list[RomScanResult] = []
