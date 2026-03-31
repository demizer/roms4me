"""Base types for the export pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ExportStep:
    """A single fix/transformation step in the export pipeline."""

    name: str
    """Short name of the step (e.g., 'strip_header', 'rename_ext')."""

    description: str
    """Human-readable description of what this step does."""

    params: dict = field(default_factory=dict)
    """Parameters for the step (e.g., {'header_size': 512, 'new_ext': '.sfc'})."""


@dataclass
class ExportPlan:
    """A plan for exporting a ROM — describes what fixes will be applied."""

    rom_file: str
    """Source ROM filename."""

    target_name: str
    """Target filename after export (DAT-correct name)."""

    steps: list[ExportStep] = field(default_factory=list)
    """Ordered list of transformations to apply."""

    @property
    def summary(self) -> str:
        """Human-readable summary of all steps."""
        if not self.steps:
            return "No changes needed"
        return " → ".join(s.name for s in self.steps)


class ExportFixer(Protocol):
    """Interface for a single export fix heuristic."""

    name: str
    """Human-readable name of this fixer."""

    def suggest(self, rom_file: Path, rom_data: bytes, dat_game_name: str,
                dat_rom_name: str, dat_rom_ext: str) -> list[ExportStep]:
        """Suggest export fix steps for a ROM file.

        Args:
            rom_file: Path to the ROM file
            rom_data: Raw ROM data (already extracted from zip if needed)
            dat_game_name: The matched DAT game name
            dat_rom_name: The expected ROM filename from DAT (e.g., 'Game (USA).sfc')
            dat_rom_ext: The expected extension (e.g., '.sfc')

        Returns list of ExportStep to apply. Empty if no fix needed.
        """
        ...
