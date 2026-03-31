"""Base handler protocol — defines the interface all system handlers implement."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from roms4me.models.dat import DatFile
from roms4me.models.scan import GameScanResult

ProgressCallback = Callable[[str, bool], None]
"""Called with (message, is_transient).

is_transient=True means the message is a progress update that should
replace the previous transient message (e.g., a progress bar).
is_transient=False means it's a permanent log line.
"""


class SystemHandler(Protocol):
    """Interface for system-specific ROM handling.

    Each handler knows how to:
    - Scan: match files in a ROM directory against a DAT using CRC
    - Fix: rename/reorganize matched ROMs to match DAT names
    - Export: package ROMs for a target device/directory
    """

    name: str
    """Human-readable handler name."""

    extensions: list[str]
    """File extensions this handler recognizes (e.g., [".sfc", ".smc"])."""

    def scan(
        self,
        dat: DatFile,
        rom_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> list[GameScanResult]:
        """Scan a ROM directory against a DAT file. Returns results per game."""
        ...

    def fix(self, dat: DatFile, rom_dir: Path, output_dir: Path) -> int:
        """Rename/zip ROMs to match DAT names. Returns count of fixed ROMs.

        Reads from rom_dir, writes corrected files to output_dir.
        Does not modify rom_dir in place.
        """
        ...
