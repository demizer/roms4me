"""Tests for the /api/rom-details endpoint and related helpers.

Covers:
- _rom_type helper: loose file returns own extension
- _rom_type helper: zip with single ROM file returns inner extension
- _rom_type helper: zip with mixed files (README + ROM) returns ROM extension
- _rom_type helper: zip with accepted_exts whitelist selects ROM over larger non-ROM
- rom_details endpoint: returns 404 for unknown system
- rom_details endpoint: exists=True and correct file metadata for a zip on disk
- rom_details endpoint: embedded files listed correctly (name, type, size, crc)
- rom_details endpoint: compressed=True for zip, rom_type derived from embedded files
"""

import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

from roms4me.api.routes import _rom_type


# ---------------------------------------------------------------------------
# _rom_type helper — no HTTP layer needed
# ---------------------------------------------------------------------------


def test_rom_type_loose_file(tmp_path):
    """A loose .sfc file returns 'sfc'."""
    rom = tmp_path / "Game (USA).sfc"
    rom.write_bytes(b"\x00" * 64)
    assert _rom_type(rom) == "sfc"


def test_rom_type_zip_single_entry(tmp_path):
    """A zip with one .z64 entry returns 'z64'."""
    zip_path = tmp_path / "Game (USA).zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Game (USA).z64", b"\x80\x37" + b"\x00" * 62)
    assert _rom_type(zip_path) == "z64"


def test_rom_type_zip_prefers_rom_over_readme(tmp_path):
    """A zip with README.txt and a .v64 ROM returns 'v64', not 'txt'."""
    zip_path = tmp_path / "Game (USA).zip"
    rom_data = b"\x37\x80" + b"\xAB" * 1024  # v64 magic + body
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("README.txt", b"Thank you for downloading!\n" * 10)
        zf.writestr("Game (USA).v64", rom_data)
    # Without whitelist: falls back to largest file (v64 > txt)
    assert _rom_type(zip_path) == "v64"


def test_rom_type_zip_whitelist_selects_rom(tmp_path):
    """With accepted_exts, a small ROM is chosen over a large non-ROM."""
    zip_path = tmp_path / "Game.zip"
    # Make the non-ROM file larger so fallback-by-size would pick it
    big_readme = b"x" * 5000
    small_rom = b"\x80\x37" + b"\x00" * 100  # z64 magic, only 102 bytes
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("README.txt", big_readme)
        zf.writestr("Game.z64", small_rom)
    result = _rom_type(zip_path, accepted_exts={".z64", ".v64", ".n64"})
    assert result == "z64"


# ---------------------------------------------------------------------------
# /api/rom-details endpoint — uses TestClient with patched dependencies
# ---------------------------------------------------------------------------


def _make_zip_with_files(zip_path: Path, files: list[tuple[str, bytes]]) -> Path:
    """Write a zip containing the given (name, data) pairs."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, data in files:
            zf.writestr(name, data)
    return zip_path


@pytest.fixture()
def _detail_env(tmp_path):
    """Set up a minimal environment for testing the rom_details endpoint.

    Patches get_data_dir / get_config_path in every module that imports them
    directly (not just the paths module) and resets the DB engine singleton so
    each test gets a fresh, isolated database.
    """
    import roms4me.core.paths as paths_mod
    import roms4me.core.database as db_mod
    import roms4me.core.migrate_config as migrate_mod

    app_dir = tmp_path / "appdata"
    app_dir.mkdir()

    _gdd = lambda: app_dir  # noqa: E731
    _gcp = lambda: app_dir / "config.toml"  # noqa: E731

    # Patch every module that holds a direct reference to these functions
    saved = {
        "paths_gdd": paths_mod.get_data_dir,
        "paths_gcp": paths_mod.get_config_path,
        "db_gdd": db_mod.get_data_dir,
        "migrate_gdd": migrate_mod.get_data_dir,
        "migrate_gcp": migrate_mod.get_config_path,
        "engine": db_mod._engine,
    }

    paths_mod.get_data_dir = _gdd
    paths_mod.get_config_path = _gcp
    db_mod.get_data_dir = _gdd
    migrate_mod.get_data_dir = _gdd
    migrate_mod.get_config_path = _gcp
    db_mod._engine = None  # force fresh engine for this test

    yield tmp_path, app_dir

    paths_mod.get_data_dir = saved["paths_gdd"]
    paths_mod.get_config_path = saved["paths_gcp"]
    db_mod.get_data_dir = saved["db_gdd"]
    migrate_mod.get_data_dir = saved["migrate_gdd"]
    migrate_mod.get_config_path = saved["migrate_gcp"]
    db_mod._engine = saved["engine"]


def _make_client(tmp_path, rom_dir: Path, system_name: str = "Nintendo 64"):
    """Return a TestClient with a seeded DB and config for the given ROM dir."""
    from fastapi.testclient import TestClient
    from roms4me.app import create_app
    from roms4me.core.database import get_session
    from roms4me.models.db import System as SystemModel

    app = create_app()
    client = TestClient(app, raise_server_exceptions=True)

    # Seed System into DB so the endpoint can find it
    with get_session() as session:
        sys_obj = SystemModel(name=system_name)
        session.add(sys_obj)
        session.commit()
        session.refresh(sys_obj)
        system_id = sys_obj.id

    # Patch _resolve_paths to return our ROM dir for this system
    from roms4me.api import routes as routes_mod

    class _FakePath:
        def __init__(self, path, sid):
            self.path = str(path)
            self.system_id = sid

    def _fake_resolve(sess):
        return [], [_FakePath(rom_dir, system_id)]

    return client, system_name, system_id, _fake_resolve


def test_rom_details_not_found_system(_detail_env):
    """Unknown system name returns 404."""
    tmp_path, app_dir = _detail_env
    from fastapi.testclient import TestClient
    from roms4me.app import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/rom-details/NonExistentSystem9999", params={"file": "game.zip"})
    assert resp.status_code == 404


def test_rom_details_zip_exists_and_metadata(_detail_env):
    """Zip on disk: exists=True, compressed=True, embedded files listed."""
    tmp_path, app_dir = _detail_env
    rom_dir = tmp_path / "roms"
    rom_dir.mkdir()

    rom_data = b"\x37\x80" + b"\xBE" * 2048  # v64 magic
    readme_data = b"readme text here\n"
    zip_path = _make_zip_with_files(
        rom_dir / "Game (USA).zip",
        [
            ("README.txt", readme_data),
            ("Game (USA).v64", rom_data),
        ],
    )

    client, system_name, system_id, _fake_resolve = _make_client(tmp_path, rom_dir)

    from roms4me.api import routes as routes_mod

    with patch.object(routes_mod, "_resolve_paths", _fake_resolve):
        resp = client.get(
            f"/api/rom-details/{system_name}",
            params={"file": "Game (USA).zip"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["exists"] is True
    assert data["compressed"] is True
    assert data["file_type"] == "zip"
    assert data["size"] == zip_path.stat().st_size
    assert len(data["embedded"]) == 2


def test_rom_details_embedded_file_fields(_detail_env):
    """Each embedded file entry has name, type, size, compress_size, crc."""
    tmp_path, app_dir = _detail_env
    rom_dir = tmp_path / "roms"
    rom_dir.mkdir()

    rom_data = b"\x80\x37" + b"\xCC" * 512  # z64 magic
    _make_zip_with_files(
        rom_dir / "Game.zip",
        [("Game.z64", rom_data)],
    )
    expected_crc = f"{zlib.crc32(rom_data) & 0xFFFFFFFF:08x}"

    client, system_name, system_id, _fake_resolve = _make_client(tmp_path, rom_dir)

    from roms4me.api import routes as routes_mod

    with patch.object(routes_mod, "_resolve_paths", _fake_resolve):
        resp = client.get(
            f"/api/rom-details/{system_name}",
            params={"file": "Game.zip"},
        )

    data = resp.json()
    assert data["exists"] is True
    entry = next(e for e in data["embedded"] if e["name"] == "Game.z64")
    assert entry["type"] == "z64"
    assert entry["size"] == len(rom_data)
    assert entry["crc"] == expected_crc
    assert "compress_size" in entry


def test_rom_details_rom_type_from_embedded(_detail_env):
    """rom_type is derived from the largest embedded file when no DB row exists."""
    tmp_path, app_dir = _detail_env
    rom_dir = tmp_path / "roms"
    rom_dir.mkdir()

    rom_data = b"\x37\x80" + b"\xAA" * 1024  # v64, larger than readme
    readme = b"short readme"
    _make_zip_with_files(
        rom_dir / "WWF.zip",
        [("README.txt", readme), ("WWF No Mercy (USA).v64", rom_data)],
    )

    client, system_name, system_id, _fake_resolve = _make_client(tmp_path, rom_dir)

    from roms4me.api import routes as routes_mod

    with patch.object(routes_mod, "_resolve_paths", _fake_resolve):
        resp = client.get(
            f"/api/rom-details/{system_name}",
            params={"file": "WWF.zip"},
        )

    data = resp.json()
    assert data["rom_type"] == "v64"


def test_rom_details_not_on_disk(_detail_env):
    """File that doesn't exist on disk returns exists=False."""
    tmp_path, app_dir = _detail_env
    rom_dir = tmp_path / "roms"
    rom_dir.mkdir()

    client, system_name, system_id, _fake_resolve = _make_client(tmp_path, rom_dir)

    from roms4me.api import routes as routes_mod

    with patch.object(routes_mod, "_resolve_paths", _fake_resolve):
        resp = client.get(
            f"/api/rom-details/{system_name}",
            params={"file": "ghost.zip"},
        )

    data = resp.json()
    assert data["exists"] is False
    assert data["size"] == 0
    assert data["embedded"] == []
