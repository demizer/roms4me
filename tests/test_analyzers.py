"""Tests for NameContainsAnalyzer and pipeline error surfacing.

Covers:
- NameContainsAnalyzer: exact base name match returns suggestion with confidence=0.9
- NameContainsAnalyzer: partial match (ROM base inside DAT name)
- NameContainsAnalyzer: reverse partial match (DAT base inside ROM name)
- NameContainsAnalyzer: short base names are ignored
- Pipeline error surfacing: analyzer exceptions appear in result.errors
- Pipeline error surfacing: errors don't crash the pipeline
"""

from roms4me.analyzers import pipeline as pl
from roms4me.analyzers.name_contains import NameContainsAnalyzer
from roms4me.analyzers.pipeline import analyze_rom
from roms4me.models.dat import DatFile, GameEntry, RomEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dat(*game_names: str, crc: str = "aabbccdd") -> DatFile:
    """Build a minimal DatFile with the given game names."""
    games = [
        GameEntry(
            name=name,
            description=name,
            roms=[RomEntry(name=f"{name}.bin", size=128, crc=crc)],
        )
        for name in game_names
    ]
    return DatFile(name="Test DAT", file_path="", games=games)


# ---------------------------------------------------------------------------
# NameContainsAnalyzer — exact base name match
# ---------------------------------------------------------------------------


def test_exact_base_name_match_returns_high_confidence():
    """ROM base name exactly matches DAT entry base name → confidence=0.9, exact match reason."""
    dat = _make_dat("WWF No Mercy (USA) (Rev 1)")
    analyzer = NameContainsAnalyzer()

    suggestions = analyzer.analyze("WWF No Mercy (USA) (Rev 1)", dat)

    assert len(suggestions) >= 1
    best = suggestions[0]
    assert best.dat_game_name == "WWF No Mercy (USA) (Rev 1)"
    assert best.confidence == 0.9
    assert "Exact base name match" in best.reason


def test_exact_base_name_match_no_tags():
    """ROM filename without tags still matches DAT entry with tags."""
    dat = _make_dat("Tetris (USA)")
    analyzer = NameContainsAnalyzer()

    suggestions = analyzer.analyze("Tetris", dat)

    # "Tetris" base == "Tetris" base from "Tetris (USA)" → exact match
    assert any(s.dat_game_name == "Tetris (USA)" for s in suggestions)
    exact = next(s for s in suggestions if s.dat_game_name == "Tetris (USA)")
    assert exact.confidence == 0.9
    assert "Exact base name match" in exact.reason


def test_exact_match_is_ranked_above_partial():
    """When DAT has both an exact match and a partial match, exact is ranked first."""
    dat = _make_dat("Spawn (USA)", "Todd McFarlane's Spawn - The Video Game (USA)")
    analyzer = NameContainsAnalyzer()

    suggestions = analyzer.analyze("Spawn (U)", dat)

    # Exact match for "Spawn (USA)" should come first
    assert suggestions[0].dat_game_name == "Spawn (USA)"
    assert suggestions[0].confidence == 0.9


def test_partial_match_rom_base_in_dat_name():
    """ROM base name found inside a longer DAT entry name."""
    dat = _make_dat("Todd McFarlane's Spawn - The Video Game (USA)")
    analyzer = NameContainsAnalyzer()

    suggestions = analyzer.analyze("Spawn (U)", dat)

    assert len(suggestions) == 1
    assert suggestions[0].dat_game_name == "Todd McFarlane's Spawn - The Video Game (USA)"
    assert suggestions[0].confidence < 0.9  # lower than exact match
    assert "Spawn" in suggestions[0].reason


def test_partial_match_dat_base_in_rom_name():
    """DAT base name found inside a longer ROM name."""
    dat = _make_dat("Tetris (USA)")
    analyzer = NameContainsAnalyzer()

    # ROM name contains the full DAT base
    suggestions = analyzer.analyze("Super Tetris Challenge (USA)", dat)

    assert any(s.dat_game_name == "Tetris (USA)" for s in suggestions)


def test_short_base_name_returns_empty():
    """Base names under 3 characters produce no suggestions (too ambiguous)."""
    dat = _make_dat("EA Sports (USA)")
    analyzer = NameContainsAnalyzer()

    suggestions = analyzer.analyze("EA (U)", dat)

    assert suggestions == []


def test_no_match_returns_empty():
    """Completely unrelated ROM and DAT produce no suggestions."""
    dat = _make_dat("Super Mario Bros (USA)")
    analyzer = NameContainsAnalyzer()

    assert analyzer.analyze("Zelda (U)", dat) == []


# ---------------------------------------------------------------------------
# Pipeline error surfacing
# ---------------------------------------------------------------------------


def test_analyzer_exception_populates_errors(tmp_path):
    """When a file-based analyzer raises, the error appears in result.errors."""
    rom = tmp_path / "Game (USA).nes"
    rom.write_bytes(b"\x00" * 128)
    dat = _make_dat("Game (USA)")

    bad_analyzer = type(
        "BadAnalyzer",
        (),
        {"name": "bad", "analyze_file": lambda self, p, d, crc="": (_ for _ in ()).throw(RuntimeError("disk on fire"))},
    )()

    original = pl.BASE_FILE_ANALYZERS
    pl.BASE_FILE_ANALYZERS = [bad_analyzer]
    try:
        result = analyze_rom(rom, dat, verify_crc=False)
    finally:
        pl.BASE_FILE_ANALYZERS = original

    assert any("bad" in e for e in result.errors)
    assert any("disk on fire" in e for e in result.errors)


def test_analyzer_exception_does_not_crash_pipeline(tmp_path):
    """A crashing analyzer doesn't prevent the rest of the pipeline from running."""
    rom = tmp_path / "Tetris (USA).nes"
    rom.write_bytes(b"\x00" * 128)
    # Give the DAT a matching game so the name-based analyzer finds something
    dat = _make_dat("Tetris (USA)")

    from roms4me.analyzers import pipeline as pl

    bad_analyzer = type(
        "BadAnalyzer",
        (),
        {"name": "bad", "analyze_file": lambda self, p, d, crc="": (_ for _ in ()).throw(RuntimeError("oops"))},
    )()

    original = pl.BASE_FILE_ANALYZERS
    pl.BASE_FILE_ANALYZERS = [bad_analyzer]
    try:
        result = analyze_rom(rom, dat, verify_crc=False)
    finally:
        pl.BASE_FILE_ANALYZERS = original

    # Pipeline should still produce name-based suggestions
    assert len(result.suggestions) > 0
    # And the error should be recorded
    assert len(result.errors) > 0


def test_name_analyzer_exception_populates_errors(tmp_path):
    """When a name-based analyzer raises, the error appears in result.errors."""
    rom = tmp_path / "Tetris (USA).nes"
    rom.write_bytes(b"\x00" * 128)
    dat = _make_dat("Tetris (USA)")

    from roms4me.analyzers import pipeline as pl

    bad_analyzer = type(
        "BadNameAnalyzer",
        (),
        {"name": "bad_name", "analyze": lambda self, stem, d: (_ for _ in ()).throw(ValueError("name boom"))},
    )()

    original = pl.NAME_ANALYZERS
    pl.NAME_ANALYZERS = [bad_analyzer]
    try:
        result = analyze_rom(rom, dat, verify_crc=False)
    finally:
        pl.NAME_ANALYZERS = original

    assert any("name boom" in e for e in result.errors)
