"""Unit tests for the export executor, planner, and region priority filtering.

Tests cover:
- Simple repackage (clean .sfc in zip → correct output zip)
- SNES copier header stripping (.smc with 512-byte zero header)
- Extension rename as part of header-strip flow (.smc → .sfc)
- Overwriting an existing file at the destination
- Destination directory creation
- plan_export() + execute_export() end-to-end
- Zip with embedded readme: plan removes non-essential file, no bogus rename_ext
- Executor: zip with embedded non-ROM picks correct ROM file to export
- Region priority helpers: base name extraction, region extraction, filtering logic
"""

import zipfile
import zlib
from pathlib import Path

import pytest

from roms4me.exporters.base import ExportPlan, ExportStep
from roms4me.exporters.executor import execute_export


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zip(path: Path, inner_name: str, data: bytes) -> Path:
    """Write a zip at path containing one file named inner_name with data."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(inner_name, data)
    return path


def _zip_inner(zip_path: Path) -> tuple[str, bytes]:
    """Return (filename, data) of the first entry in a zip."""
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.infolist()[0]
        return info.filename, zf.read(info.filename)


def _snes_header_rom(rom_body: bytes) -> bytes:
    """Return bytes that look like a copier-headered SNES ROM.

    512 zero bytes (header) followed by rom_body.
    rom_body must be a multiple of 1024 bytes.
    """
    assert len(rom_body) % 1024 == 0, "rom_body must be a multiple of 1024"
    return b"\x00" * 512 + rom_body


def _make_dat(name: str, rom_name: str, data: bytes) -> "DatFile":
    """Build a minimal DatFile object for one game."""
    from roms4me.models.dat import DatFile, GameEntry, RomEntry

    crc = f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
    rom = RomEntry(name=rom_name, size=len(data), crc=crc)
    game = GameEntry(name=name, description=name, roms=[rom])
    return DatFile(
        name="Test DAT",
        file_path="",
        games=[game],
    )


# ---------------------------------------------------------------------------
# execute_export: ExportPlan built manually
# ---------------------------------------------------------------------------


def test_simple_compress_package(tmp_path):
    """ROM already has correct extension — plan only needs compress_package."""
    rom_data = b"clean sfc rom data"
    src = _make_zip(tmp_path / "Game (USA).zip", "Game (USA).sfc", rom_data)
    dest = tmp_path / "output"

    plan = ExportPlan(
        rom_file="Game (USA).zip",
        target_name="Game (USA).zip",
        steps=[
            ExportStep(
                name="compress_package",
                description="Package correctly",
                params={"zip_name": "Game (USA).zip", "inner_name": "Game (USA).sfc"},
            )
        ],
    )

    out = execute_export(src, plan, dest)

    assert out == dest / "Game (USA).zip"
    inner_name, inner_data = _zip_inner(out)
    assert inner_name == "Game (USA).sfc"
    assert inner_data == rom_data


def test_strip_header_and_rename(tmp_path):
    """Loose .smc with 512-byte zero header — strip header, zip as .sfc."""
    rom_body = b"A" * 16384  # 16 KB, multiple of 1024
    src = tmp_path / "Game (USA).smc"
    src.write_bytes(_snes_header_rom(rom_body))
    dest = tmp_path / "output"

    plan = ExportPlan(
        rom_file="Game (USA).smc",
        target_name="Game (USA).zip",
        steps=[
            ExportStep(
                name="strip_header",
                description="Strip 512-byte copier header",
                params={"header_size": 512, "source_ext": ".smc"},
            ),
            ExportStep(
                name="rename_ext",
                description="Rename: .smc → .sfc",
                params={"from_ext": ".smc", "to_ext": ".sfc"},
            ),
            ExportStep(
                name="compress_package",
                description="Package as zip",
                params={"zip_name": "Game (USA).zip", "inner_name": "Game (USA).sfc"},
            ),
        ],
    )

    out = execute_export(src, plan, dest)

    assert out == dest / "Game (USA).zip"
    inner_name, inner_data = _zip_inner(out)
    assert inner_name == "Game (USA).sfc"
    assert inner_data == rom_body  # header stripped


def test_strip_header_from_zipped_smc(tmp_path):
    """Zipped .smc with 512-byte header — strip header, repackage as .sfc zip."""
    rom_body = b"B" * 8192  # 8 KB
    src = _make_zip(tmp_path / "Game (Japan).zip", "Game (Japan).smc", _snes_header_rom(rom_body))
    dest = tmp_path / "output"

    plan = ExportPlan(
        rom_file="Game (Japan).zip",
        target_name="Game (Japan).zip",
        steps=[
            ExportStep(
                name="strip_header",
                description="Strip 512-byte copier header",
                params={"header_size": 512, "source_ext": ".smc"},
            ),
            ExportStep(
                name="compress_package",
                description="Package as zip",
                params={"zip_name": "Game (Japan).zip", "inner_name": "Game (Japan).sfc"},
            ),
        ],
    )

    out = execute_export(src, plan, dest)

    inner_name, inner_data = _zip_inner(out)
    assert inner_name == "Game (Japan).sfc"
    assert inner_data == rom_body


def test_overwrite_existing_file(tmp_path):
    """Existing file at destination is overwritten."""
    rom_data = b"new rom data"
    src = _make_zip(tmp_path / "Game (USA).zip", "Game (USA).sfc", rom_data)
    dest = tmp_path / "output"
    dest.mkdir()

    # Pre-existing stale file
    stale = dest / "Game (USA).zip"
    stale.write_bytes(b"old stale data")

    plan = ExportPlan(
        rom_file="Game (USA).zip",
        target_name="Game (USA).zip",
        steps=[
            ExportStep(
                name="compress_package",
                description="Package",
                params={"zip_name": "Game (USA).zip", "inner_name": "Game (USA).sfc"},
            )
        ],
    )

    out = execute_export(src, plan, dest)

    _, inner_data = _zip_inner(out)
    assert inner_data == rom_data  # not the stale content


def test_creates_dest_dir(tmp_path):
    """Destination directory (including parents) is created if absent."""
    rom_data = b"rom"
    src = _make_zip(tmp_path / "Game.zip", "Game.sfc", rom_data)
    dest = tmp_path / "deep" / "nested" / "sdcard"

    plan = ExportPlan(
        rom_file="Game.zip",
        target_name="Game.zip",
        steps=[
            ExportStep(
                name="compress_package",
                description="Package",
                params={"zip_name": "Game.zip", "inner_name": "Game.sfc"},
            )
        ],
    )

    out = execute_export(src, plan, dest)

    assert dest.is_dir()
    assert out.exists()


def test_no_steps_copies_file(tmp_path):
    """Empty plan copies source to destination using target_name."""
    rom_data = b"already correct"
    src = _make_zip(tmp_path / "Game (USA).zip", "Game (USA).sfc", rom_data)
    dest = tmp_path / "output"

    plan = ExportPlan(
        rom_file="Game (USA).zip",
        target_name="Game (USA).zip",
        steps=[],
    )

    out = execute_export(src, plan, dest)

    assert out == dest / "Game (USA).zip"
    # Copied zip is valid and contains the same data
    _, inner_data = _zip_inner(out)
    assert inner_data == rom_data


# ---------------------------------------------------------------------------
# plan_export() + execute_export() end-to-end
# ---------------------------------------------------------------------------


def test_plan_and_execute_clean_sfc(tmp_path):
    """Clean .sfc (already correct) — plan has only compress_package, output is correct."""
    from roms4me.analyzers.base import Suggestion
    from roms4me.exporters.planner import plan_export

    rom_data = b"super mario world data"
    src = _make_zip(tmp_path / "Super Mario World (USA).zip", "Super Mario World (USA).sfc", rom_data)
    dat = _make_dat("Super Mario World (USA)", "Super Mario World (USA).sfc", rom_data)

    suggestion = Suggestion(
        dat_game_name="Super Mario World (USA)",
        confidence=1.0,
        reason="",
        crc_match=True,
    )

    plan = plan_export(src, suggestion, dat)
    dest = tmp_path / "sdcard"
    out = execute_export(src, plan, dest)

    assert out.name == "Super Mario World (USA).zip"
    inner_name, inner_data = _zip_inner(out)
    assert inner_name == "Super Mario World (USA).sfc"
    assert inner_data == rom_data


def test_plan_and_execute_snes_header(tmp_path):
    """SNES .smc with copier header — plan strips header, renames, zips."""
    from roms4me.analyzers.base import Suggestion
    from roms4me.exporters.planner import plan_export

    rom_body = b"C" * 32768  # 32 KB
    headered = _snes_header_rom(rom_body)
    src = tmp_path / "Contra III (USA).smc"
    src.write_bytes(headered)

    dat = _make_dat("Contra III (USA)", "Contra III (USA).sfc", rom_body)

    suggestion = Suggestion(
        dat_game_name="Contra III (USA)",
        confidence=1.0,
        reason="",
        crc_match=True,
    )

    plan = plan_export(src, suggestion, dat)
    step_names = [s.name for s in plan.steps]
    assert "strip_header" in step_names
    assert "compress_package" in step_names

    dest = tmp_path / "sdcard"
    out = execute_export(src, plan, dest)

    assert out.name == "Contra III (USA).zip"
    inner_name, inner_data = _zip_inner(out)
    assert inner_name == "Contra III (USA).sfc"
    assert inner_data == rom_body  # header gone


def test_plan_and_execute_overwrites_old_collection(tmp_path):
    """Old collection on SD card is overwritten when exporting."""
    from roms4me.analyzers.base import Suggestion
    from roms4me.exporters.planner import plan_export

    rom_data = b"donkey kong country data"
    src = _make_zip(tmp_path / "Donkey Kong Country (USA).zip", "Donkey Kong Country (USA).sfc", rom_data)
    dat = _make_dat("Donkey Kong Country (USA)", "Donkey Kong Country (USA).sfc", rom_data)

    dest = tmp_path / "sdcard"
    dest.mkdir()
    # Simulate old/corrupt copy already on SD card
    (dest / "Donkey Kong Country (USA).zip").write_bytes(b"old corrupt data")

    suggestion = Suggestion(
        dat_game_name="Donkey Kong Country (USA)",
        confidence=1.0,
        reason="",
        crc_match=True,
    )

    plan = plan_export(src, suggestion, dat)
    out = execute_export(src, plan, dest)

    _, inner_data = _zip_inner(out)
    assert inner_data == rom_data  # fresh copy, not the old one


def test_plan_removes_non_essential_embedded_files(tmp_path):
    """Zip with ROM (.z64) + readme (.txt): plan has remove_embedded for txt, no rename_ext."""
    from roms4me.analyzers.base import Suggestion
    from roms4me.exporters.planner import plan_export
    from roms4me.models.dat import DatFile, GameEntry, RomEntry

    z64_data = b"\x80\x37" + b"\xAB" * 4096  # N64 BigEndian magic + body
    crc = f"{zlib.crc32(z64_data) & 0xFFFFFFFF:08x}"
    rom_name = "WWF No Mercy (USA) (Rev 1).z64"

    zip_path = tmp_path / "WWF No Mercy (USA) (Rev 1).zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", b"This ROM was downloaded from the internet.\n")
        zf.writestr(rom_name, z64_data)

    game = GameEntry(
        name="WWF No Mercy (USA) (Rev 1)",
        description="WWF No Mercy (USA) (Rev 1)",
        roms=[RomEntry(name=rom_name, size=len(z64_data), crc=crc)],
    )
    # DAT name must match a known system pattern so get_rom_extensions returns N64 extensions
    dat = DatFile(name="Nintendo - Nintendo 64", file_path="", games=[game])

    suggestion = Suggestion(
        dat_game_name="WWF No Mercy (USA) (Rev 1)",
        confidence=1.0,
        reason="",
        crc_match=True,
    )

    plan = plan_export(zip_path, suggestion, dat)
    step_names = [s.name for s in plan.steps]

    # Must have remove_embedded for the txt readme
    remove_steps = [s for s in plan.steps if s.name == "remove_embedded"]
    assert len(remove_steps) == 1, f"Expected 1 remove_embedded step, got: {step_names}"
    assert "readme.txt" in remove_steps[0].params["filename"]

    # Must NOT suggest renaming .txt → .z64 (the .z64 is already there)
    rename_steps = [s for s in plan.steps if s.name == "rename_ext"]
    assert rename_steps == [], f"Unexpected rename_ext step(s): {[s.description for s in rename_steps]}"

    # Must have compress_package as the final step
    assert "compress_package" in step_names


def test_execute_zip_with_embedded_readme_exports_rom(tmp_path):
    """Executor reads the .z64 ROM from a zip that also contains a readme."""
    z64_data = b"\x80\x37" + b"\xCC" * 2048
    rom_name = "WWF No Mercy (USA) (Rev 1).z64"

    zip_path = tmp_path / "WWF No Mercy (USA) (Rev 1).zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", b"This ROM was downloaded from the internet.\n")
        zf.writestr(rom_name, z64_data)

    dest = tmp_path / "output"
    plan = ExportPlan(
        rom_file="WWF No Mercy (USA) (Rev 1).zip",
        target_name="WWF No Mercy (USA) (Rev 1).zip",
        steps=[
            ExportStep(
                name="remove_embedded",
                description="Remove non-essential embedded file: readme.txt",
                params={"filename": "readme.txt"},
            ),
            ExportStep(
                name="compress_package",
                description=f"Package as: WWF No Mercy (USA) (Rev 1).zip containing {rom_name}",
                params={"zip_name": "WWF No Mercy (USA) (Rev 1).zip", "inner_name": rom_name},
            ),
        ],
    )

    out = execute_export(zip_path, plan, dest)

    inner_name, inner_data = _zip_inner(out)
    assert inner_name == rom_name
    assert inner_data == z64_data  # the ROM, not the readme


# ---------------------------------------------------------------------------
# Region priority helpers (_extract_base_name, _extract_region, _apply_region_priority)
# ---------------------------------------------------------------------------


def test_extract_base_name_strips_tags():
    from roms4me.api.routes import _extract_base_name

    assert _extract_base_name("Perfect Dark (USA)") == "Perfect Dark"
    assert _extract_base_name("Super Mario World (USA) (Rev 1)") == "Super Mario World"
    assert _extract_base_name("Tetris") == "Tetris"


def test_extract_region_returns_first_parens():
    from roms4me.api.routes import _extract_region

    assert _extract_region("Perfect Dark (USA)") == "USA"
    assert _extract_region("Perfect Dark (Europe) (En,Fr,De,Es,It)") == "Europe"
    assert _extract_region("Perfect Dark (USA) (Rev 1)") == "USA"
    assert _extract_region("Tetris") == ""


def test_region_priority_excludes_lower_regions():
    """USA preferred → Europe and Japan files excluded."""
    from roms4me.api.routes import _apply_region_priority

    files = [
        ("Perfect Dark (USA).zip", "Perfect Dark (USA)"),
        ("Perfect Dark (Europe).zip", "Perfect Dark (Europe)"),
        ("Perfect Dark (Japan).zip", "Perfect Dark (Japan)"),
    ]
    excluded = _apply_region_priority(files, ["USA", "World", "Europe", "Japan"])
    assert "Perfect Dark (USA).zip" not in excluded
    assert "Perfect Dark (Europe).zip" in excluded
    assert "Perfect Dark (Japan).zip" in excluded


def test_region_priority_falls_back_to_world():
    """No USA version present → World is kept, Japan excluded."""
    from roms4me.api.routes import _apply_region_priority

    files = [
        ("Tetris (World).zip", "Tetris (World)"),
        ("Tetris (Japan).zip", "Tetris (Japan)"),
    ]
    excluded = _apply_region_priority(files, ["USA", "World", "Europe", "Japan"])
    assert "Tetris (World).zip" not in excluded
    assert "Tetris (Japan).zip" in excluded


def test_region_priority_single_file_not_excluded():
    """Single file in a group is never excluded."""
    from roms4me.api.routes import _apply_region_priority

    excluded = _apply_region_priority(
        [("Game (USA).zip", "Game (USA)")], ["USA", "World", "Europe", "Japan"]
    )
    assert excluded == set()


def test_region_priority_empty_list_no_filtering():
    """Empty priority list disables region filtering."""
    from roms4me.api.routes import _apply_region_priority

    files = [
        ("Game (USA).zip", "Game (USA)"),
        ("Game (Japan).zip", "Game (Japan)"),
    ]
    assert _apply_region_priority(files, []) == set()


def test_region_priority_keeps_both_revisions_of_same_region():
    """Two USA revisions score equally — both are kept."""
    from roms4me.api.routes import _apply_region_priority

    files = [
        ("Perfect Dark (USA).zip", "Perfect Dark (USA)"),
        ("Perfect Dark (USA) (Rev 1).zip", "Perfect Dark (USA) (Rev 1)"),
    ]
    excluded = _apply_region_priority(files, ["USA", "World", "Europe", "Japan"])
    assert excluded == set()


def test_region_priority_independent_per_game_title():
    """Filtering is applied per base title, not across the whole list."""
    from roms4me.api.routes import _apply_region_priority

    files = [
        ("Mario (USA).zip", "Mario (USA)"),
        ("Mario (Japan).zip", "Mario (Japan)"),
        ("Zelda (USA).zip", "Zelda (USA)"),
        ("Zelda (Europe).zip", "Zelda (Europe)"),
    ]
    excluded = _apply_region_priority(files, ["USA", "World", "Europe", "Japan"])
    assert excluded == {"Mario (Japan).zip", "Zelda (Europe).zip"}
