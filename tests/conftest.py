"""Shared fixtures for playwright tests."""

import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest
import uvicorn


@pytest.fixture(scope="session")
def _test_data_dir():
    """Create a temporary data directory with test DATs and ROMs."""
    tmpdir = Path(tempfile.mkdtemp(prefix="roms4me_test_"))

    # Create test ROM directories
    rom_root = tmpdir / "ROMS"
    snes_dir = rom_root / "Nintendo - SNES"
    snes_dir.mkdir(parents=True)

    # Create some fake ROM zips
    import zipfile

    for name, crc_data in [
        ("Game Alpha (USA)", b"alpha rom data here"),
        ("Game Beta (Japan)", b"beta rom data here"),
        ("Game Gamma Test (Europe)", b"gamma test rom data"),
        ("Game Delta (USA)", b"delta rom data here"),
        ("Test Suite (World)", b"test suite rom data"),
    ]:
        zip_path = snes_dir / f"{name}.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(f"{name}.sfc", crc_data)

    # Create test DAT directory with a DAT file
    dat_dir = tmpdir / "DATs"
    dat_dir.mkdir(parents=True)

    import zlib

    # Build DAT XML with CRCs matching the fake ROMs
    games_xml = ""
    for name, data in [
        ("Game Alpha (USA)", b"alpha rom data here"),
        ("Game Beta (Japan)", b"beta rom data here"),
        ("Game Gamma Test (Europe)", b"gamma test rom data"),
        ("Game Delta (USA)", b"delta rom data here"),
        ("Test Suite (World)", b"test suite rom data"),
        ("Missing Game 1 (USA)", b""),
        ("Missing Game 2 (Japan)", b""),
        ("Another Test Missing (Europe)", b""),
    ]:
        crc = f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" if data else "00000000"
        size = len(data)
        games_xml += f"""
  <game name="{name}">
    <description>{name}</description>
    <rom name="{name}.sfc" size="{size}" crc="{crc}"/>
  </game>"""

    dat_content = f"""<?xml version="1.0"?>
<datafile>
  <header>
    <name>Nintendo - Super Nintendo Entertainment System (Parent-Clone)</name>
    <description>Test SNES DAT</description>
    <version>20260101-000000</version>
  </header>
{games_xml}
</datafile>"""

    dat_file = dat_dir / "Nintendo - Super Nintendo Entertainment System (Parent-Clone) (20260101-000000).dat"
    dat_file.write_text(dat_content)

    yield tmpdir

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(scope="session")
def _app_server(_test_data_dir):
    """Start the roms4me server on a test port with a temp database."""
    # Override data dir to use temp
    os.environ["ROMS4ME_DATA_DIR"] = str(_test_data_dir / "appdata")

    # Patch get_data_dir to use our temp dir
    import roms4me.core.paths as paths_mod

    original_get_data_dir = paths_mod.get_data_dir
    paths_mod.get_data_dir = lambda: _test_data_dir / "appdata"

    from roms4me.app import create_app

    app = create_app()
    port = 18765

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to start
    import urllib.request

    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            break
        except Exception:
            time.sleep(0.2)

    yield {
        "url": f"http://127.0.0.1:{port}",
        "data_dir": _test_data_dir,
        "rom_root": _test_data_dir / "ROMS",
        "dat_dir": _test_data_dir / "DATs",
    }

    server.should_exit = True
    paths_mod.get_data_dir = original_get_data_dir


@pytest.fixture(scope="session")
def browser_type_launch_args():
    """Use Firefox for playwright tests."""
    return {"headless": True}


@pytest.fixture(scope="session")
def browser_context_args():
    """Browser context args."""
    return {"viewport": {"width": 1400, "height": 900}}


@pytest.fixture()
def app(page, _app_server):
    """Navigate to the app and provide server info."""
    page.goto(_app_server["url"])
    page.wait_for_load_state("networkidle")
    return _app_server
