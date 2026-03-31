"""DAT file parser supporting CLRMamePro and MAME XML formats."""

import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from roms4me.models.dat import DatFile, GameEntry, RomEntry

log = logging.getLogger(__name__)


def parse_dat_file(path: Path) -> DatFile:
    """Parse a DAT file and return structured data.

    Supports both plain .dat XML files and .zip archives containing a .dat file.
    """
    log.info("Parsing DAT file: %s", path)
    xml_bytes = _read_dat_content(path)
    root = ET.fromstring(xml_bytes)

    header = root.find("header")
    name = _text(header, "name") if header is not None else path.stem
    description = _text(header, "description") if header is not None else ""
    version = _text(header, "version") if header is not None else ""
    author = _text(header, "author") if header is not None else ""

    games: list[GameEntry] = []
    for game_el in root.iter("game"):
        game_name = game_el.get("name", "")
        game_desc = _text(game_el, "description")
        roms: list[RomEntry] = []
        for rom_el in game_el.iter("rom"):
            roms.append(
                RomEntry(
                    name=rom_el.get("name", ""),
                    size=int(rom_el.get("size", "0")),
                    crc=rom_el.get("crc", ""),
                    md5=rom_el.get("md5", ""),
                    sha1=rom_el.get("sha1", ""),
                )
            )
        games.append(GameEntry(name=game_name, description=game_desc, roms=roms))

    log.info("Parsed %d games from %s", len(games), path.name)
    return DatFile(
        name=name,
        description=description,
        version=version,
        author=author,
        file_path=str(path),
        games=games,
    )


def detect_system(path: Path) -> str:
    """Detect the system name from a DAT file's header.

    Returns the <name> field from the header, stripping common suffixes
    like "(Parent-Clone)" or version dates.
    """
    xml_bytes = _read_dat_content(path)
    root = ET.fromstring(xml_bytes)
    header = root.find("header")
    if header is None:
        return path.stem
    raw_name = _text(header, "name")
    if not raw_name:
        return path.stem
    return _clean_system_name(raw_name)


def scan_dat_dir(directory: Path) -> list[dict[str, str]]:
    """Scan a directory for DAT files (.dat and .zip) and return their system names."""
    results: list[dict[str, str]] = []
    for ext in ("*.dat", "*.zip"):
        for f in sorted(directory.glob(ext)):
            try:
                system = detect_system(f)
                results.append({
                    "file": f.name,
                    "path": str(f),
                    "system": system,
                })
            except Exception:
                log.warning("Could not parse DAT file: %s", f)
    return results


def _read_dat_content(path: Path) -> bytes:
    """Read DAT XML content from a plain file or a zip archive."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            dat_names = [n for n in zf.namelist() if n.lower().endswith(".dat")]
            if not dat_names:
                # Fall back to first XML-looking file
                dat_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not dat_names:
                raise ValueError(f"No .dat or .xml file found in {path}")
            return zf.read(dat_names[0])
    return path.read_bytes()


def _clean_system_name(raw_name: str) -> str:
    """Clean a DAT header name into a system name.

    Strips suffixes like "(Parent-Clone)", "(Decrypted)", dates, etc.
    "Nintendo - Game Boy (Parent-Clone)" -> "Nintendo - Game Boy"
    """
    import re

    # Remove parenthesized suffixes that are metadata, not system names
    # Keep ones that are part of the system (e.g., "TurboGrafx-16")
    metadata_patterns = [
        r"\s*\(Parent-Clone\)",
        r"\s*\(Headerless\)",
        r"\s*\(Decrypted\)",
        r"\s*\(Encrypted\)",
        r"\s*\(BigEndian\)",
        r"\s*\(LittleEndian\)",
        r"\s*\(Multiboot\)",
        r"\s*\(Download Play\)",
        r"\s*\(PSN\)",
        r"\s*\(A2R\)",
        r"\s*\(\d{8}-\d{6}\)",  # Date stamps
    ]
    name = raw_name
    for pattern in metadata_patterns:
        name = re.sub(pattern, "", name)
    return name.strip()


def _text(parent: ET.Element, tag: str) -> str:
    """Extract text from a child element, returning empty string if missing."""
    el = parent.find(tag)
    return el.text.strip() if el is not None and el.text else ""
