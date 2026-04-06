"""Base types for the analyzer pipeline."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from roms4me.models.dat import DatFile


@dataclass
class Suggestion:
    """A candidate match for an unmatched ROM file."""

    dat_game_name: str
    """The DAT game entry we think this ROM is."""

    confidence: float
    """Confidence score 0.0 - 1.0."""

    reason: str
    """Human-readable explanation of why we think this is a match."""

    expected_crc: str = ""
    """CRC from the DAT entry."""

    actual_crc: str = ""
    """CRC computed from the ROM file."""

    crc_match: bool | None = None
    """True = CRC confirmed, False = CRC mismatch, None = not yet checked."""

    action: str = ""
    """Suggested action: 'rename', 'crc_mismatch', 'manual'."""


@dataclass
class AnalysisResult:
    """Result of analyzing a single ROM file."""

    rom_file: str
    """The ROM filename."""

    suggestions: list[Suggestion] = field(default_factory=list)
    """Ranked list of candidate matches, best first."""

    errors: list[str] = field(default_factory=list)
    """Analyzer errors or warnings to surface to the user."""

    rom_inner_type: str = ""
    """Extension of the primary ROM file inside an archive (e.g. 'v64', 'sfc').
    Empty for loose ROM files (use the file's own extension instead).
    Populated by the pipeline so callers can update the DB without re-reading the zip."""

    @property
    def best(self) -> Suggestion | None:
        """Return the highest-confidence suggestion, or None."""
        return self.suggestions[0] if self.suggestions else None


class Analyzer(Protocol):
    """Interface for a single analysis heuristic."""

    name: str
    """Human-readable name of this analyzer."""

    def analyze(self, rom_stem: str, dat: DatFile) -> list[Suggestion]:
        """Analyze a ROM filename against a DAT and return candidate matches.

        Should return suggestions sorted by confidence, highest first.
        Does NOT do CRC verification — that's handled by the pipeline.
        """
        ...
