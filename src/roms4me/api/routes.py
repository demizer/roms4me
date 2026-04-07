"""API routes for roms4me."""

import logging
import platform
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select, func

from roms4me.core.config import add_dat_path as config_add_dat, add_rom_path as config_add_rom
from roms4me.core.config import load_config, remove_dat_path as config_remove_dat
from roms4me.core.config import remove_rom_path as config_remove_rom
from roms4me.core.database import get_session
from roms4me.models.db import DatPath, PrescanInfo, RomPath, ScanMeta, ScanResult, System
from roms4me.services.dat_parser import parse_dat_file, scan_dat_dir

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _rom_type(rom_file: Path, accepted_exts: set[str] | None = None) -> str:
    """Return the inner ROM extension for an archive, or the file's own extension.

    For zip files, peeks at the central directory to find the primary ROM file
    using the system's accepted extension whitelist. Falls back to the largest file.
    Returns the extension without a leading dot, e.g. 'z64', 'sfc', 'zip'.
    """
    suffix = rom_file.suffix.lower()
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(rom_file) as zf:
                entries = [e for e in zf.infolist() if not e.is_dir()]
                if accepted_exts:
                    candidates = [e for e in entries if Path(e.filename).suffix.lower() in accepted_exts]
                    if not candidates:
                        candidates = entries
                else:
                    candidates = entries
                if candidates:
                    best = max(candidates, key=lambda e: e.file_size)
                    inner = Path(best.filename).suffix.lower().lstrip(".")
                    return inner if inner else "zip"
        except Exception:
            pass
    return suffix.lstrip(".")


class _ResolvedPath:
    """Lightweight shim so scan code can use .path and .system_id like the old DB models."""

    __slots__ = ("path", "system_id")

    def __init__(self, path: str, system_id: int):
        self.path = path
        self.system_id = system_id


def _resolve_paths(session) -> tuple[list[_ResolvedPath], list[_ResolvedPath]]:
    """Load config and resolve entries to system IDs, creating System rows as needed.

    Returns (dat_paths, rom_paths) with .path and .system_id attributes.
    """
    cfg = load_config()
    dat_resolved = []
    rom_resolved = []

    for entry in cfg.dat_paths:
        system = session.exec(select(System).where(System.name == entry.system)).first()
        if not system:
            system = System(name=entry.system)
            session.add(system)
            session.commit()
            session.refresh(system)
        dat_resolved.append(_ResolvedPath(entry.path, system.id))

    for entry in cfg.rom_paths:
        system = session.exec(select(System).where(System.name == entry.system)).first()
        if not system:
            system = System(name=entry.system)
            session.add(system)
            session.commit()
            session.refresh(system)
        rom_resolved.append(_ResolvedPath(entry.path, system.id))

    return dat_resolved, rom_resolved




class PathOnly(BaseModel):
    path: str


class DatPathRequest(BaseModel):
    path: str


# --- Utilities ---


@router.post("/open-path")
async def open_path(req: PathOnly) -> dict[str, str]:
    """Open a file or directory in the system file manager."""
    p = Path(req.path)
    # If it's a file, open the parent directory
    target = str(p.parent if p.is_file() else p)
    system = platform.system()
    try:
        match system:
            case "Linux":
                subprocess.Popen(["xdg-open", target])
            case "Darwin":
                subprocess.Popen(["open", target])
            case "Windows":
                subprocess.Popen(["explorer", target])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "opened"}


class RomPathRequest(BaseModel):
    path: str
    system: str


# --- Systems ---


@router.get("/systems")
async def list_systems() -> list[System]:
    """List all systems."""
    with get_session() as session:
        return list(session.exec(select(System)).all())


# --- DAT paths ---


@router.get("/dats/paths")
async def list_dat_paths() -> list[dict]:
    """List all configured DAT directories with detected systems."""
    cfg = load_config()
    return [
        {"path": entry.path, "system": entry.system}
        for entry in cfg.dat_paths
    ]


@router.post("/dats/paths")
async def add_dat_path(req: DatPathRequest) -> list[dict]:
    """Add a DAT directory path. Auto-detects systems from DAT file headers."""
    p = Path(req.path).expanduser().resolve()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Directory does not exist")

    discovered = scan_dat_dir(p)
    if not discovered:
        raise HTTPException(status_code=400, detail="No DAT files found in directory")

    added: list[dict] = []
    with get_session() as session:
        for dat_info in discovered:
            system_name = dat_info["system"]
            # Ensure System row exists in DB (scan results reference it)
            system = session.exec(
                select(System).where(System.name == system_name)
            ).first()
            if not system:
                system = System(name=system_name)
                session.add(system)
                session.commit()

            config_add_dat(dat_info["path"], system_name)
            added.append({"path": dat_info["path"], "system": system_name})

    log.info("Added %d DAT files from %s", len(added), p)
    return added


@router.delete("/dats/paths")
async def remove_dat_path(req: dict) -> dict[str, str]:
    """Remove a DAT path entry."""
    path = req.get("path", "")
    system = req.get("system", "")
    if not path:
        raise HTTPException(status_code=400, detail="Path required")
    config_remove_dat(path, system)
    return {"status": "removed"}


# --- DAT files ---


@router.get("/dats")
async def list_dats() -> list[dict[str, str]]:
    """List all DAT files from all configured paths."""
    cfg = load_config()
    results: list[dict[str, str]] = []
    for entry in cfg.dat_paths:
        p = Path(entry.path)
        if p.exists():
            results.append({
                "name": p.stem,
                "path": str(p),
                "system": entry.system,
            })
    return results


@router.get("/dats/{dat_name}")
async def get_dat(dat_name: str):
    """Parse and return a DAT file's contents."""
    cfg = load_config()
    for entry in cfg.dat_paths:
        p = Path(entry.path)
        if p.stem == dat_name and p.exists():
            return parse_dat_file(p)
    raise HTTPException(status_code=404, detail="DAT file not found")


# --- ROM paths ---


@router.get("/roms/paths")
async def list_rom_paths() -> list[dict]:
    """List all configured ROM directories with system names."""
    cfg = load_config()
    return [
        {"path": entry.path, "system": entry.system}
        for entry in cfg.rom_paths
    ]


@router.post("/roms/paths")
async def add_rom_path(req: RomPathRequest) -> list[dict]:
    """Add ROM directory path(s).

    If `system` is provided, adds the single path for that system.
    If `system` is empty, scans subdirectories and auto-matches to known systems.
    """
    p = Path(req.path).expanduser().resolve()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Directory does not exist")

    if req.system:
        result = _add_single_rom_path(p, req.system)
        return [result] if result else []

    subdirs = sorted([d.name for d in p.iterdir() if d.is_dir()])
    if not subdirs:
        raise HTTPException(status_code=400, detail="No subdirectories found")

    added: list[dict] = []
    for subdir_name in subdirs:
        result = _add_single_rom_path(p / subdir_name, subdir_name)
        if result:
            added.append(result)
    return added


def _add_single_rom_path(p: Path, system_name: str) -> dict | None:
    """Add a single ROM path for a system. Returns the result dict, or None if duplicate."""
    cfg = load_config()
    # Check for duplicate
    for entry in cfg.rom_paths:
        if entry.path == str(p) and entry.system == system_name:
            return None

    # Ensure System row exists in DB
    with get_session() as session:
        system = session.exec(select(System).where(System.name == system_name)).first()
        if not system:
            system = System(name=system_name)
            session.add(system)
            session.commit()

    config_add_rom(str(p), system_name)
    log.info("Added ROM path: %s [%s]", p, system_name)
    return {"path": str(p), "system": system_name}


@router.delete("/roms/paths")
async def remove_rom_path(req: dict) -> dict[str, str]:
    """Remove a ROM directory path."""
    path = req.get("path", "")
    system = req.get("system", "")
    if not path:
        raise HTTPException(status_code=400, detail="Path required")
    config_remove_rom(path, system)
    return {"status": "removed"}


# --- Stats ---


@router.get("/stats")
async def get_stats() -> dict:
    """Return overview stats for the welcome page."""
    cfg = load_config()
    with get_session() as session:
        system_count = len(session.exec(select(System)).all())
        dat_count = len(cfg.dat_paths)
        rom_count = len(cfg.rom_paths)
        scan_count = len(session.exec(select(ScanResult)).all())

        meta = session.exec(select(ScanMeta)).first()
        last_scan = meta.last_scan.isoformat() if meta and meta.last_scan else None

        # Detect stale scan data: systems with results but no config path
        config_systems = {e.system for e in cfg.rom_paths}
        all_systems = {s.id: s.name for s in session.exec(select(System)).all()}
        result_system_ids = {sr.system_id for sr in session.exec(select(ScanResult)).all()}
        systems_with_results = {all_systems[sid] for sid in result_system_ids if sid in all_systems}
        stale_systems = sorted(systems_with_results - config_systems)

    return {
        "systems": system_count,
        "dat_files": dat_count,
        "rom_paths": rom_count,
        "scanned_games": scan_count,
        "last_scan": last_scan,
        "stale_systems": stale_systems,
    }


@router.get("/prescan")
async def prescan() -> list[dict]:
    """Pre-scan all systems: cheap DAT vs ROM compatibility check."""
    from roms4me.services.prescan import prescan_system

    results = []
    with get_session() as session:
        dat_paths, rom_paths = _resolve_paths(session)
        systems = {s.id: s.name for s in session.exec(select(System)).all()}

        rom_dirs_by_system: dict[int, list[Path]] = {}
        for rp in rom_paths:
            rom_dirs_by_system.setdefault(rp.system_id, []).append(Path(rp.path))

        for dp in dat_paths:
            if dp.system_id not in rom_dirs_by_system:
                continue
            p = Path(dp.path)
            if not p.exists():
                continue

            system_name = systems.get(dp.system_id, "Unknown")
            dat = parse_dat_file(p)

            for rom_dir in rom_dirs_by_system[dp.system_id]:
                if not rom_dir.is_dir():
                    continue
                result = prescan_system(dat, rom_dir)
                result.system = system_name
                results.append(result.to_dict())

    return results


@router.get("/scan-log")
async def get_scan_log() -> dict:
    """Return the saved log from the last scan."""
    with get_session() as session:
        meta = session.exec(select(ScanMeta)).first()
        if not meta or not meta.log:
            return {"log": None}
        return {"log": meta.log}


# --- Refresh (pre-scan only) ---


@router.post("/refresh")
async def refresh(req: dict | None = None) -> dict:
    """Start a pre-scan in a background thread. Returns immediately.

    Optional body: {"system_name": "Nintendo - N64"} to sync one system only.
    Omit body (or pass no system_name) to sync all systems.
    """
    import threading
    import roms4me.core.scan_log as scan_log_mod
    from roms4me.core.scan_log import ScanLog

    system_name = (req or {}).get("system_name") or None

    if scan_log_mod.scan_running:
        return {"status": "already_running"}

    scan = ScanLog()
    scan_log_mod.current_scan = scan
    scan_log_mod.scan_running = True

    def run():
        try:
            _do_prescan(scan, system_name)
        finally:
            scan_log_mod.scan_running = False

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return {"status": "started"}


@router.get("/refresh/status")
async def refresh_status() -> dict:
    """Poll for pre-scan/scan progress."""
    import roms4me.core.scan_log as scan_log_mod

    scan = scan_log_mod.current_scan
    if not scan:
        return {"messages": [], "done": True, "timestamp": "", "updated_rows": []}

    msgs, done, timestamp, updated_rows = scan.get_pending()
    return {
        "messages": [{"text": text, "transient": tr} for text, tr in msgs],
        "done": done,
        "timestamp": timestamp,
        "updated_rows": updated_rows,
    }


def _do_prescan(scan, system_name: str | None = None):
    """Run pre-scan: match each ROM directory to DATs using system matcher, then check compatibility.

    If system_name is given, only that system's data is cleared and re-scanned.
    If None, all systems are cleared and re-scanned.
    """
    from roms4me.services.prescan import prescan_system
    from roms4me.services.system_matcher import match_system

    if system_name:
        scan.info(f"Syncing {system_name}...", color="blue")
    else:
        scan.info("Starting pre-scan...")

    with get_session() as session:
        dat_paths, rom_paths = _resolve_paths(session)
        systems = {s.id: s.name for s in session.exec(select(System)).all()}

        if system_name:
            # Single-system sync: only clear and re-process this system
            target = session.exec(select(System).where(System.name == system_name)).first()
            if not target:
                scan.info(f"System not found: {system_name}", color="red")
                scan.finish("")
                return
            for r in session.exec(select(PrescanInfo).where(PrescanInfo.system_id == target.id)).all():
                session.delete(r)
            for r in session.exec(select(ScanResult).where(ScanResult.system_id == target.id)).all():
                session.delete(r)
            session.commit()
            rom_paths = [rp for rp in rom_paths if rp.system_id == target.id]
        else:
            # Full sync: clear all results and remove stale systems
            for r in session.exec(select(PrescanInfo)).all():
                session.delete(r)
            for r in session.exec(select(ScanResult)).all():
                session.delete(r)

            config_systems = {e.system for e in load_config().rom_paths}
            config_systems |= {e.system for e in load_config().dat_paths}
            for sys in session.exec(select(System)).all():
                if sys.name not in config_systems:
                    session.delete(sys)
                    scan.info(f"  Removed stale system: {sys.name}")
            session.commit()

        # Build DAT system name -> list of DatPath
        dat_system_names = []
        dats_by_name: dict[str, list] = {}
        for dp in dat_paths:
            name = systems.get(dp.system_id, "Unknown")
            dats_by_name.setdefault(name, []).append(dp)
            if name not in dat_system_names:
                dat_system_names.append(name)

        scan.info(f"Found {len(dat_paths)} DAT file(s), {len(rom_paths)} ROM path(s)")

        # Process each ROM directory
        checked = 0
        total_rom_dirs = len(rom_paths)
        for i, rp in enumerate(rom_paths):
            rom_dir = Path(rp.path)
            if not rom_dir.is_dir():
                continue

            rom_system = systems.get(rp.system_id, rom_dir.name)

            # Find matching DAT system using fuzzy matcher
            matched_dat_system = match_system(rom_system, dat_system_names)

            scan.info(f"[{i + 1}/{total_rom_dirs}] {rom_system}", color="blue")

            if not matched_dat_system:
                scan.info(f"  No matching DAT found")
                checked += 1
                continue

            # Process each DAT that matches this ROM dir
            matched_dats = dats_by_name[matched_dat_system]
            for dp in matched_dats:
                p = Path(dp.path)
                if not p.exists():
                    continue

                dat_filename = p.name
                scan.info(f"  DAT: {dat_filename}")

                dat = parse_dat_file(p)
                result = prescan_system(dat, rom_dir)

                icon = {"green": "✓", "yellow": "⚠", "red": "✗"}[result.rating]
                scan.info(
                    f"  {icon} {result.rating.upper()}: "
                    f"{result.rom_file_count} files, "
                    f"{result.dat_game_count} games in DAT, "
                    f"{result.name_matches} name matches",
                    color=result.rating,
                )
                scan.info(f"    {result.reason}")

                # Store prescan info (use ROM system_id so sidebar can find it)
                session.add(PrescanInfo(
                    system_id=rp.system_id,
                    rating=result.rating,
                    reason=result.reason,
                    dat_game_count=result.dat_game_count,
                    dat_extensions=",".join(sorted(result.dat_extensions)),
                    rom_file_count=result.rom_file_count,
                    rom_extensions=",".join(sorted(result.rom_extensions)),
                    name_matches=result.name_matches,
                ))

                # Store per-game matches (use ROM system_id)
                from roms4me.handlers.registry import get_rom_extensions
                _accepted_exts = set(get_rom_extensions(dat.name)) or None
                unmatched_count = 0
                for gm in result.games:
                    if gm.unmatched:
                        status = "unmatched"
                        unmatched_count += 1
                    elif gm.matched_file:
                        status = "unverified"
                    else:
                        status = "missing"
                    rom_file_path = Path(rp.path) / gm.matched_file if gm.matched_file else None
                    session.add(ScanResult(
                        system_id=rp.system_id,
                        game_name=gm.game_name,
                        description=gm.description,
                        file_name=gm.matched_file,
                        rom_type=_rom_type(rom_file_path, _accepted_exts) if rom_file_path and rom_file_path.exists() else "",
                        expected_file_name=f"{gm.game_name}.zip" if not gm.unmatched else "",
                        status=status,
                        note=gm.note,
                    ))
                if unmatched_count > 0:
                    scan.info(f"    {unmatched_count} ROM files with no DAT match")

            checked += 1

        session.commit()

        # Update timestamp
        meta = session.exec(select(ScanMeta)).first()
        now = datetime.now(timezone.utc)
        if meta:
            meta.last_scan = now
            meta.log = scan.text()
        else:
            meta = ScanMeta(last_scan=now, log=scan.text())
            session.add(meta)
        session.commit()

    scan.info(f"Pre-scan complete: {checked} system(s) checked", color="green")
    scan.finish(now.isoformat())


# --- Per-system CRC hash scan ---


@router.post("/scan/{system_name}")
async def scan_system(system_name: str) -> dict:
    """Start a CRC hash scan for a single system. Returns immediately."""
    import threading
    import roms4me.core.scan_log as scan_log_mod
    from roms4me.core.scan_log import ScanLog

    if scan_log_mod.scan_running:
        return {"status": "already_running"}

    scan = ScanLog()
    scan_log_mod.current_scan = scan
    scan_log_mod.scan_running = True

    def run():
        try:
            _do_system_scan(scan, system_name)
        finally:
            scan_log_mod.scan_running = False

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return {"status": "started"}


def _do_system_scan(scan, system_name: str):
    """Run CRC hash scan for a single system (called from background thread)."""
    from roms4me.handlers.registry import get_handler
    from roms4me.services.system_matcher import match_system

    scan.info(f"Starting CRC scan for {system_name}...")

    with get_session() as session:
        system = session.exec(select(System).where(System.name == system_name)).first()
        if not system:
            scan.info(f"System not found: {system_name}")
            scan.finish("")
            return

        all_dats, all_roms = _resolve_paths(session)
        rom_paths = [rp for rp in all_roms if rp.system_id == system.id]
        if not rom_paths:
            scan.info("No ROM paths configured for this system")
            scan.finish("")
            return

        # Find matching DATs using system matcher
        all_systems = {s.id: s.name for s in session.exec(select(System)).all()}
        dat_system_names = list({all_systems.get(dp.system_id, "") for dp in all_dats})
        matched_dat_system = match_system(system_name, dat_system_names)

        if not matched_dat_system:
            scan.info("No matching DAT files found for this system")
            scan.finish("")
            return

        dat_paths = [dp for dp in all_dats if all_systems.get(dp.system_id) == matched_dat_system]
        rom_dirs = [Path(rp.path) for rp in rom_paths]

        scan.info(f"  Matched DAT system: {matched_dat_system} ({len(dat_paths)} DAT file(s))")

        # Clear old scan results for this system
        old = session.exec(select(ScanResult).where(ScanResult.system_id == system.id)).all()
        for r in old:
            session.delete(r)
        session.commit()

        handler = get_handler(system_name)
        total = 0

        for dp in dat_paths:
            p = Path(dp.path)
            if not p.exists():
                continue

            scan.info(f"  DAT: {p.name}")
            dat = parse_dat_file(p)
            scan.info(f"  {len(dat.games)} games in DAT")

            for rom_dir in rom_dirs:
                if not rom_dir.is_dir():
                    continue
                rom_file_count = sum(1 for f in rom_dir.iterdir() if f.is_file())
                scan.info(f"  Scanning {rom_dir.name}/ ({rom_file_count} files)...")

                results = handler.scan(
                    dat, rom_dir,
                    on_progress=lambda msg, transient=False: scan.info(msg, transient=transient),
                )

                ok = sum(1 for r in results if r.status == "ok")
                missing = sum(1 for r in results if r.status == "missing")
                other = len(results) - ok - missing

                from roms4me.handlers.registry import get_rom_extensions
                _scan_exts = set(get_rom_extensions(dat.name)) or None
                for gr in results:
                    gr_path = rom_dir / gr.file_name if gr.file_name else None
                    session.add(ScanResult(
                        system_id=system.id,
                        game_name=gr.name,
                        description=gr.description,
                        file_name=gr.file_name,
                        rom_type=_rom_type(gr_path, _scan_exts) if gr_path and gr_path.exists() else "",
                        expected_file_name=gr.expected_file_name,
                        status=gr.status,
                    ))
                total += len(results)

                scan.info(f"  ✓ {ok} ok, ✗ {missing} missing, ? {other} other")

                # Find ROM files not matched by CRC and add as "unmatched"
                from roms4me.services.prescan import find_closest_dat_match

                matched_files = {gr.file_name for gr in results if gr.file_name}
                dat_game_names = [g.name for g in dat.games]
                unmatched_count = 0
                for f in rom_dir.iterdir():
                    if not f.is_file():
                        continue
                    file_matched = False
                    for mf in matched_files:
                        if f.name in mf:
                            file_matched = True
                            break
                    if not file_matched:
                        _, reason = find_closest_dat_match(f.stem, dat_game_names)
                        session.add(ScanResult(
                            system_id=system.id,
                            game_name=f.stem,
                            description=f.stem,
                            file_name=f.name,
                            rom_type=_rom_type(f, _scan_exts),
                            expected_file_name="",
                            status="unmatched",
                            note=reason,
                        ))
                        unmatched_count += 1

                if unmatched_count > 0:
                    scan.info(f"  {unmatched_count} ROM files with no CRC match")

            session.commit()

        session.commit()

    scan.info(f"CRC scan complete: {total} games", color="green")
    scan.finish("")


# --- Results ---


@router.get("/prescan-results")
async def get_prescan_results() -> list[dict]:
    """Get all pre-scan results with system names."""
    with get_session() as session:
        infos = session.exec(select(PrescanInfo)).all()
        results = []
        for info in infos:
            system = session.get(System, info.system_id)
            results.append({
                "system": system.name if system else "Unknown",
                "rating": info.rating,
                "reason": info.reason,
                "dat_game_count": info.dat_game_count,
                "dat_extensions": info.dat_extensions,
                "rom_file_count": info.rom_file_count,
                "rom_extensions": info.rom_extensions,
                "name_matches": info.name_matches,
            })
        return results


@router.post("/analyze/{system_name}")
async def analyze_roms(system_name: str, req: dict) -> dict:
    """Start analysis of selected ROMs in a background thread.

    Expects {"files": ["file1.zip", "file2.zip", ...]}.
    Poll /api/refresh/status for progress.
    """
    import threading
    import roms4me.core.scan_log as scan_log_mod
    from roms4me.core.scan_log import ScanLog

    files = list(dict.fromkeys(req.get("files", [])))  # deduplicate, preserve order
    if not files:
        raise HTTPException(status_code=400, detail="No files specified")

    if scan_log_mod.scan_running:
        return {"status": "already_running"}

    scan = ScanLog()
    scan_log_mod.current_scan = scan
    scan_log_mod.scan_running = True

    def run():
        try:
            _do_analyze(scan, system_name, files)
        finally:
            scan_log_mod.scan_running = False

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return {"status": "started"}


def _do_analyze(scan, system_name: str, files: list[str]):
    """Run analysis on selected ROMs (called from background thread)."""
    from roms4me.analyzers.pipeline import analyze_rom
    from roms4me.exporters.planner import plan_export
    from roms4me.services.system_matcher import match_system

    scan.info(f"Analyzing {len(files)} ROM(s)...", color="blue")

    with get_session() as session:
        system = session.exec(select(System).where(System.name == system_name)).first()
        if not system:
            scan.info("System not found", color="red")
            scan.finish("")
            return

        all_dats, all_roms = _resolve_paths(session)
        rom_dirs = [Path(rp.path) for rp in all_roms if rp.system_id == system.id]

        # Find matching DATs
        all_systems = {s.id: s.name for s in session.exec(select(System)).all()}
        dat_system_names = list({all_systems.get(dp.system_id, "") for dp in all_dats})
        matched_dat_system = match_system(system_name, dat_system_names)

        if not matched_dat_system:
            scan.info("No matching DAT found", color="red")
            scan.finish("")
            return

        dat_path_entries = [dp for dp in all_dats if all_systems.get(dp.system_id) == matched_dat_system]
        dats = [parse_dat_file(Path(dp.path)) for dp in dat_path_entries if Path(dp.path).exists()]

        total_dat_games = sum(len(d.games) for d in dats)
        scan.info(f"DAT: {matched_dat_system} ({total_dat_games} games loaded)", color="blue")
        if not dats:
            scan.info("  No DAT files could be loaded — check DAT paths in Settings", color="red")
            scan.finish("")
            return

        matched_files: dict[str, str] = {}  # file_name -> matched game_name

        for i, filename in enumerate(files):
            pct = round((i + 1) / len(files) * 100)
            scan.info(f"[{i + 1}/{len(files)}] ({pct}%) {filename}", color="blue")
            file_log_start = len(scan.lines)

            # Find the actual file on disk
            rom_file = None
            for rom_dir in rom_dirs:
                candidate = rom_dir / filename
                if candidate.exists():
                    rom_file = candidate
                    break

            if not rom_file:
                scan.info(f"  File not found", color="red")
                continue

            # Run analysis against each DAT, surfacing any analyzer errors
            all_suggestions = []
            rom_inner_type = ""  # populated from first analysis result
            for dat in dats:
                analysis = analyze_rom(rom_file, dat, verify_crc=True)
                all_suggestions.extend(analysis.suggestions)
                if analysis.rom_inner_type and not rom_inner_type:
                    rom_inner_type = analysis.rom_inner_type
                for err in analysis.errors:
                    scan.info(f"  Note: {err}", color="yellow")

            # Deduplicate and sort
            seen = set()
            unique_suggestions = []
            for s in sorted(all_suggestions, key=lambda x: x.confidence, reverse=True):
                if s.dat_game_name not in seen:
                    seen.add(s.dat_game_name)
                    unique_suggestions.append(s)

            # Log results
            if not unique_suggestions:
                from roms4me.analyzers.pipeline import _compute_crc
                from roms4me.analyzers.n64_byteorder import _read_rom_data as _n64_read, detect_n64_format
                crc = _compute_crc(rom_file)
                diag = f"CRC: {crc}" if crc else "CRC: unknown"
                rom_bytes = _n64_read(rom_file)
                if rom_bytes:
                    fmt = detect_n64_format(rom_bytes)
                    if fmt:
                        diag += f", N64 format detected: {fmt}"
                scan.info(f"  No matches found ({diag})")
                continue

            for s in unique_suggestions[:3]:
                if s.crc_match is True:
                    scan.info(f"  ✓ {s.dat_game_name}", color="green")
                    scan.info(f"        {s.reason}")
                    scan.info(f"            - CRC MATCH: {s.actual_crc}")
                elif s.crc_match is False:
                    scan.info(f"  ✗ {s.dat_game_name}", color="red")
                    scan.info(f"        {s.reason}")
                    scan.info(f"            - CRC MISMATCH")
                    scan.info(f"            - Expected: {s.expected_crc}")
                    scan.info(f"            - Actual:   {s.actual_crc}")
                else:
                    scan.info(f"  ? {s.dat_game_name}")
                    scan.info(f"        {s.reason}")

            # If all suggestions are CRC mismatches, show diagnostic with all N64 conversion attempts
            all_mismatch = unique_suggestions and all(s.crc_match is False for s in unique_suggestions)
            if all_mismatch:
                from roms4me.analyzers.n64_byteorder import (
                    _FORMAT_LABEL,
                    _read_rom_data as _n64_read,
                    detect_n64_format,
                    to_bigendian,
                )
                import zlib as _zlib
                rom_bytes = _n64_read(rom_file)
                if rom_bytes:
                    fmt = detect_n64_format(rom_bytes)
                    if fmt:
                        # Build full DAT CRC set for quick lookup
                        dat_crcs: set[str] = set()
                        for _d in dats:
                            for _g in _d.games:
                                for _r in _g.roms:
                                    if _r.crc:
                                        dat_crcs.add(_r.crc.lower())
                        raw_crc = f"{_zlib.crc32(rom_bytes) & 0xFFFFFFFF:08x}"
                        scan.info(f"  N64 format detected: {_FORMAT_LABEL.get(fmt, fmt)}", color="yellow")
                        scan.info(f"  Raw CRC: {raw_crc} ({'in DAT' if raw_crc in dat_crcs else 'not in DAT'})", color="yellow")
                        for try_fmt in ("byteswapped", "littleendian"):
                            norm = to_bigendian(rom_bytes, try_fmt)
                            norm_crc = f"{_zlib.crc32(norm) & 0xFFFFFFFF:08x}"
                            in_dat = norm_crc in dat_crcs
                            label = _FORMAT_LABEL.get(try_fmt, try_fmt)
                            scan.info(
                                f"  Tried as {label}: {norm_crc} → {'MATCH' if in_dat else 'no match'}",
                                color="green" if in_dat else "yellow",
                            )
                    else:
                        scan.info(f"  Not recognized as N64 ROM (magic: {rom_bytes[:4].hex()})", color="yellow")

            # Update DB and build export plan only for CRC matches
            best = unique_suggestions[0]
            export_plan = None
            new_status = None
            plan_label = ""
            if best.crc_match is True:
                new_status = "matched"
                for dat in dats:
                    ep = plan_export(rom_file, best, dat, system_name=system_name)
                    if ep.steps:
                        export_plan = ep
                        break
                plan_label = "modify" if export_plan and export_plan.steps else "ok"
                if export_plan:
                    scan.info(f"  Export plan → {export_plan.target_name}", color="blue")
                    for step in export_plan.steps:
                        scan.info(f"    {step.name}: {step.description}")

            # Always update rom_type from analysis, even without a match
            if rom_inner_type:
                for row in session.exec(
                    select(ScanResult).where(
                        ScanResult.system_id == system.id,
                        ScanResult.file_name == filename,
                    )
                ).all():
                    row.rom_type = rom_inner_type
                session.commit()

            if new_status:
                all_for_file = session.exec(
                    select(ScanResult).where(
                        ScanResult.system_id == system.id,
                        ScanResult.file_name == filename,
                    )
                ).all()

                # Update the first row with the best match
                if all_for_file:
                    existing = all_for_file[0]
                    existing.status = new_status
                    existing.note = best.reason
                    existing.plan = plan_label
                    existing.game_name = best.dat_game_name
                    existing.description = best.dat_game_name
                    existing.expected_file_name = f"{best.dat_game_name}.zip"
                    if rom_inner_type:
                        existing.rom_type = rom_inner_type

                    # Remove duplicate rows for the same file (other language variants)
                    for dup in all_for_file[1:]:
                        session.delete(dup)

                    session.commit()

                    # Track matched files for cross-file cleanup below
                    matched_files[filename] = best.dat_game_name

                    # Push live row update to frontend
                    scan.row_update({
                        "game_name": existing.game_name,
                        "description": existing.description,
                        "file_name": existing.file_name,
                        "expected_file_name": existing.expected_file_name,
                        "status": existing.status,
                        "note": existing.note,
                        "plan": existing.plan or "",
                    })

            # Persist per-file log lines to every ScanResult row for this file
            file_log = "\n".join(scan.lines[file_log_start:])
            if file_log:
                for row in session.exec(
                    select(ScanResult).where(
                        ScanResult.system_id == system.id,
                        ScanResult.file_name == filename,
                    )
                ).all():
                    row.log = file_log
                session.commit()

        # Deduplicate: when multiple files match the same DAT game, keep the best one
        # (fewest export steps = closest to target format, prefer "ok" over "modify")
        matched_rows = session.exec(
            select(ScanResult).where(
                ScanResult.system_id == system.id,
                ScanResult.status == "matched",
            )
        ).all()
        by_game: dict[str, list] = {}
        for row in matched_rows:
            by_game.setdefault(row.game_name, []).append(row)

        deduped = 0
        for game_name, rows in by_game.items():
            if len(rows) < 2:
                continue
            # Sort: "ok" plan first (no modification needed), then "modify"
            rows.sort(key=lambda r: (0 if r.plan == "ok" else 1, r.file_name))
            keeper = rows[0]
            for dup in rows[1:]:
                scan.info(f"  Duplicate: {dup.file_name} → {game_name} (keeping {keeper.file_name})", color="blue")
                dup.status = "duplicate"
                dup.note = f"Duplicate of {keeper.file_name}"
                dup.plan = ""
                deduped += 1
        if deduped:
            session.commit()
            scan.info(f"  Marked {deduped} duplicate ROM(s)", color="blue")

        # Remove unverified language variants when another variant is matched.
        # E.g., if "ActRaiser (USA)" is matched, remove "ActRaiser (France)".
        import re

        def _base_name(game_name: str) -> str:
            """Strip region/language suffix to get a comparable base name."""
            return re.sub(r"\s*\([^)]*\)\s*", " ", game_name).strip().lower()

        matched_rows = session.exec(
            select(ScanResult).where(
                ScanResult.system_id == system.id,
                ScanResult.status == "matched",
            )
        ).all()
        matched_bases = {_base_name(r.game_name) for r in matched_rows}
        # Also track matched file_names for same-file dedup
        matched_file_names = {r.file_name for r in matched_rows if r.file_name}

        if matched_bases:
            stale = session.exec(
                select(ScanResult).where(
                    ScanResult.system_id == system.id,
                    ScanResult.status == "unverified",
                )
            ).all()
            removed = 0
            for row in stale:
                base = _base_name(row.game_name)
                if base in matched_bases or row.file_name in matched_file_names:
                    session.delete(row)
                    removed += 1
            if removed:
                session.commit()
                scan.info(f"  Removed {removed} duplicate language variant(s)", color="blue")

        scan.info(f"Analysis complete", color="green")
        scan.finish("")


@router.get("/matched-dats/{system_name}")
async def get_matched_dats(system_name: str) -> list[dict]:
    """Get DAT files that match a ROM system name."""
    from roms4me.services.system_matcher import match_system

    with get_session() as session:
        all_dats, _ = _resolve_paths(session)
        all_systems = {s.id: s.name for s in session.exec(select(System)).all()}
        dat_system_names = list({all_systems.get(dp.system_id, "") for dp in all_dats})
        matched = match_system(system_name, dat_system_names)

        if not matched:
            return []

        results = []
        for dp in all_dats:
            if all_systems.get(dp.system_id) == matched:
                results.append({
                    "system": matched,
                    "path": dp.path,
                    "filename": Path(dp.path).name,
                })
        return results


@router.patch("/results/{system_name}")
async def update_results(system_name: str, req: dict) -> dict:
    """Update plan field for one or more rows.

    Expects {"files": ["file1.zip", ...], "plan": "exclude"}.
    """
    files = req.get("files", [])
    plan = req.get("plan", "")
    if not files:
        raise HTTPException(status_code=400, detail="No files specified")

    with get_session() as session:
        system = session.exec(select(System).where(System.name == system_name)).first()
        if not system:
            raise HTTPException(status_code=404, detail="System not found")

        updated = 0
        for filename in files:
            rows = session.exec(
                select(ScanResult).where(
                    ScanResult.system_id == system.id,
                    ScanResult.file_name == filename,
                )
            ).all()
            for row in rows:
                row.plan = plan
                updated += 1
        session.commit()

    return {"updated": updated}


@router.post("/export/{system_name}")
async def export_roms(system_name: str, req: dict) -> dict:
    """Export ROMs to a destination directory.

    Expects {"files": ["file1.zip", ...], "dest": "/media/user/sdcard/SNES"}.
    Poll /api/refresh/status for progress.
    """
    import threading

    import roms4me.core.scan_log as scan_log_mod
    from roms4me.core.scan_log import ScanLog

    files = list(dict.fromkeys(req.get("files", [])))
    dest = req.get("dest", "").strip()
    region_priority = [r.strip() for r in req.get("region_priority", []) if r.strip()]
    archive_format = req.get("archive_format", "zip").strip().lower()
    if archive_format not in {"zip", "7z"}:
        archive_format = "zip"
    rom_only = bool(req.get("rom_only", True))

    if not files:
        raise HTTPException(status_code=400, detail="No files specified")
    if not dest:
        raise HTTPException(status_code=400, detail="No destination path specified")

    if scan_log_mod.scan_running:
        return {"status": "already_running"}

    scan = ScanLog()
    scan_log_mod.current_scan = scan
    scan_log_mod.scan_running = True

    def run():
        try:
            _do_export(scan, system_name, files, Path(dest), region_priority, archive_format, rom_only)
        finally:
            scan_log_mod.scan_running = False

    threading.Thread(target=run, daemon=True).start()
    return {"status": "started"}


def _extract_base_name(game_name: str) -> str:
    """Return the title portion of a No-Intro game name (before first parenthetical)."""
    m = re.match(r"^([^(]+)", game_name)
    return m.group(1).strip() if m else game_name.strip()


def _extract_region(game_name: str) -> str:
    """Return the first parenthetical of a No-Intro game name (typically the region)."""
    m = re.search(r"\(([^)]+)\)", game_name)
    return m.group(1) if m else ""


def _apply_region_priority(
    files_with_names: list[tuple[str, str]], region_priority: list[str]
) -> set[str]:
    """Return filenames to skip based on region preference.

    For each base-title group with more than one file, keeps the best-ranked
    region match and auto-excludes the rest.  Files with no priority match are
    treated as lowest priority.
    """
    if not region_priority:
        return set()

    groups: dict[str, list[tuple[str, str]]] = {}
    for filename, game_name in files_with_names:
        base = _extract_base_name(game_name)
        groups.setdefault(base, []).append((filename, game_name))

    def _score(item: tuple[str, str]) -> int:
        region = _extract_region(item[1])
        for idx, pref in enumerate(region_priority):
            if pref.lower() in region.lower():
                return idx
        return len(region_priority)

    auto_excluded: set[str] = set()
    for group in groups.values():
        if len(group) <= 1:
            continue
        best = min(_score(item) for item in group)
        for filename, game_name in group:
            if _score((filename, game_name)) > best:
                auto_excluded.add(filename)

    return auto_excluded


def _do_export(scan, system_name: str, files: list[str], dest_dir: Path,
               region_priority: list[str] | None = None, archive_format: str = "zip",
               rom_only: bool = True):
    """Execute exports for selected ROMs (called from background thread)."""
    from roms4me.analyzers.base import Suggestion
    from roms4me.exporters.executor import execute_export
    from roms4me.exporters.planner import plan_export
    from roms4me.services.system_matcher import match_system

    region_priority = region_priority or []
    scan.info(f"Exporting {len(files)} ROM(s) to {dest_dir}...", color="blue")

    with get_session() as session:
        system = session.exec(select(System).where(System.name == system_name)).first()
        if not system:
            scan.info("System not found", color="red")
            scan.finish("")
            return

        all_dats, all_roms = _resolve_paths(session)
        rom_dirs = [Path(rp.path) for rp in all_roms if rp.system_id == system.id]

        all_systems = {s.id: s.name for s in session.exec(select(System)).all()}
        dat_system_names = list({all_systems.get(dp.system_id, "") for dp in all_dats})
        matched_dat_system = match_system(system_name, dat_system_names)

        if not matched_dat_system:
            scan.info("No matching DAT found", color="red")
            scan.finish("")
            return

        dat_path_entries = [dp for dp in all_dats if all_systems.get(dp.system_id) == matched_dat_system]
        dats = [parse_dat_file(Path(dp.path)) for dp in dat_path_entries if Path(dp.path).exists()]

        # Build region-priority auto-exclude set before the main loop
        auto_excluded_region: set[str] = set()
        if region_priority:
            files_with_names = []
            for fn in files:
                row = session.exec(
                    select(ScanResult).where(
                        ScanResult.system_id == system.id,
                        ScanResult.file_name == fn,
                        ScanResult.status == "matched",
                    )
                ).first()
                if row:
                    files_with_names.append((fn, row.game_name))
            auto_excluded_region = _apply_region_priority(files_with_names, region_priority)
            if auto_excluded_region:
                scan.info(
                    f"Region filter ({', '.join(region_priority)}): {len(auto_excluded_region)} lower-priority version(s) will be skipped",
                    color="blue",
                )

        exported = 0
        duplicates = 0
        excluded = 0
        failed = 0

        for i, filename in enumerate(files):
            pct = round((i + 1) / len(files) * 100)
            scan.info(f"[{i + 1}/{len(files)}] ({pct}%) {filename}", color="blue")

            if filename in auto_excluded_region:
                scan.info(f"  Region-excluded (prefer {', '.join(region_priority)})", color="yellow")
                excluded += 1
                continue

            # Use stored match from DB — no need to re-analyze
            result_row = session.exec(
                select(ScanResult).where(
                    ScanResult.system_id == system.id,
                    ScanResult.file_name == filename,
                    ScanResult.status == "matched",
                )
            ).first()

            if not result_row:
                # Look up actual status for a better error message
                any_row = session.exec(
                    select(ScanResult).where(
                        ScanResult.system_id == system.id,
                        ScanResult.file_name == filename,
                    )
                ).first()
                if any_row:
                    if any_row.plan == "exclude":
                        scan.info("  Excluded", color="yellow")
                        excluded += 1
                    elif any_row.status == "duplicate":
                        scan.info("  Skipped (duplicate)", color="yellow")
                        duplicates += 1
                    else:
                        reason = {
                            "unmatched": "no CRC match in DAT (fan translation, hack, or bad dump)",
                            "unverified": "run Analyze first",
                            "ok": "run Analyze first",
                        }.get(any_row.status, f"status: {any_row.status}")
                        scan.info(f"  Skipped ({reason})", color="yellow")
                        failed += 1
                else:
                    scan.info("  Not in database — run Scan first", color="red")
                    failed += 1
                continue

            if result_row.plan == "exclude":
                scan.info("  Excluded", color="yellow")
                excluded += 1
                continue

            # Find the source file on disk
            rom_file = None
            for rom_dir in rom_dirs:
                candidate = rom_dir / filename
                if candidate.exists():
                    rom_file = candidate
                    break

            if not rom_file:
                scan.info("  File not found on disk", color="red")
                failed += 1
                continue

            # Reconstruct a minimal suggestion from stored game_name
            suggestion = Suggestion(
                dat_game_name=result_row.game_name,
                confidence=1.0,
                reason="",
                crc_match=True,
            )

            # Build export plan (fast — reads ROM and runs fixers)
            export_plan = None
            for dat in dats:
                ep = plan_export(rom_file, suggestion, dat, system_name=system_name)
                if ep:
                    export_plan = ep
                    break

            if not export_plan:
                scan.info("  Could not build export plan", color="red")
                failed += 1
                continue

            try:
                out_path = execute_export(rom_file, export_plan, dest_dir,
                                          archive_format=archive_format, rom_only=rom_only)
                scan.info(f"  → {out_path.name}", color="green")
                exported += 1
            except OSError as e:
                scan.info(f"  Export failed: {e}", color="red")
                failed += 1

        parts = [f"{exported} exported"]
        if duplicates:
            parts.append(f"{duplicates} duplicates skipped")
        if excluded:
            parts.append(f"{excluded} excluded")
        if failed:
            parts.append(f"{failed} failed")
        color = "green" if failed == 0 else "yellow"
        scan.info(f"Export complete: {', '.join(parts)}", color=color)
        scan.finish("")


@router.get("/results/{system_name}")
async def get_results(system_name: str, view: str = "owned") -> dict:
    """Get scan results for a system.

    view=owned: ROM files the user has, with DAT match info (default)
    view=missing: DAT games the user doesn't have
    view=all: everything
    """
    with get_session() as session:
        system = session.exec(select(System).where(System.name == system_name)).first()
        if not system:
            raise HTTPException(status_code=404, detail="System not found")
        all_results = session.exec(
            select(ScanResult).where(ScanResult.system_id == system.id)
        ).all()

        owned = []      # unverified + ok + matched (by name or CRC)
        unmatched = []  # ROM files with no DAT match
        missing = []    # DAT entries with no ROM
        for r in all_results:
            entry = {
                "game_name": r.game_name,
                "description": r.description,
                "file_name": r.file_name,
                "rom_type": r.rom_type,
                "expected_file_name": r.expected_file_name,
                "status": r.status,
                "note": r.note,
                "plan": r.plan or "",
            }
            if r.status == "missing":
                missing.append(entry)
            elif r.status == "unmatched":
                unmatched.append(entry)
            else:
                owned.append(entry)

        if view == "missing":
            rows = missing
        elif view == "all":
            rows = [*owned, *unmatched, *missing]
        else:
            rows = [*owned, *unmatched]

        return {
            "rows": rows,
            "owned_count": len(owned),
            "unmatched_count": len(unmatched),
            "missing_count": len(missing),
            "total_count": len(all_results),
        }


@router.get("/rom-details/{system_name}")
async def rom_details(system_name: str, file: str) -> dict:
    """Return ZIP contents and DB rows for a single ROM file.

    Used by the 'View analysis' context menu to show embedded archive files
    and what the database currently knows about each match candidate.
    """
    with get_session() as session:
        system = session.exec(select(System).where(System.name == system_name)).first()
        if not system:
            raise HTTPException(status_code=404, detail="System not found")

        _, all_roms = _resolve_paths(session)
        rom_dirs = [Path(rp.path) for rp in all_roms if rp.system_id == system.id]

        # Locate the file on disk
        rom_file: Path | None = None
        for rom_dir in rom_dirs:
            candidate = rom_dir / file
            if candidate.exists():
                rom_file = candidate
                break

        file_size = rom_file.stat().st_size if rom_file else 0
        file_type = Path(file).suffix.lower().lstrip(".")

        # List embedded files for archives
        embedded: list[dict] = []
        archive_error: str = ""
        if rom_file and file_type == "zip":
            try:
                with zipfile.ZipFile(rom_file) as zf:
                    for info in zf.infolist():
                        if not info.is_dir():
                            inner_type = Path(info.filename).suffix.lower().lstrip(".")
                            embedded.append({
                                "name": info.filename,
                                "type": inner_type,
                                "size": info.file_size,
                                "compress_size": info.compress_size,
                                "crc": f"{info.CRC & 0xFFFFFFFF:08x}",
                            })
            except zipfile.BadZipFile:
                archive_error = "Invalid ZIP file"

        db_rows = session.exec(
            select(ScanResult).where(
                ScanResult.system_id == system.id,
                ScanResult.file_name == file,
            )
        ).all()

        # Inner ROM type: prefer DB value, fall back to inspecting embedded files
        inner_rom_type = db_rows[0].rom_type if db_rows and db_rows[0].rom_type else ""
        if not inner_rom_type and embedded:
            biggest = max(embedded, key=lambda e: e["size"])
            inner_rom_type = biggest["type"]

        # Export plan — build synchronously from the matched DB row + DAT
        export_steps: list[dict] = []
        export_target: str = ""
        matched_row = next((r for r in db_rows if r.status == "matched"), None)
        if matched_row and rom_file:
            from roms4me.analyzers.base import Suggestion as _Suggestion
            from roms4me.exporters.planner import plan_export as _plan_export
            from roms4me.services.dat_parser import parse_dat_file
            from roms4me.services.system_matcher import match_system

            all_dats, _ = _resolve_paths(session)
            all_systems_map = {s.id: s.name for s in session.exec(select(System)).all()}
            dat_system_names = list({all_systems_map.get(dp.system_id, "") for dp in all_dats})
            matched_dat_system = match_system(system_name, dat_system_names)
            if matched_dat_system:
                dat_entries = [dp for dp in all_dats if all_systems_map.get(dp.system_id) == matched_dat_system]
                for dp in dat_entries:
                    dat_path = Path(dp.path)
                    if not dat_path.exists():
                        continue
                    try:
                        dat = parse_dat_file(dat_path)
                        ep = _plan_export(
                            rom_file,
                            _Suggestion(
                                dat_game_name=matched_row.game_name,
                                confidence=1.0,
                                reason="",
                                crc_match=True,
                            ),
                            dat,
                            system_name=system_name,
                        )
                        if ep.steps:
                            export_steps = [
                                {"name": s.name, "description": s.description}
                                for s in ep.steps
                            ]
                            export_target = ep.target_name
                            break
                    except Exception as e:
                        log.warning("Could not build export plan for %s: %s", file, e)

        return {
            "file_name": file,
            "exists": rom_file is not None,
            "size": file_size,
            "file_type": file_type,
            "compressed": file_type in {"zip", "7z"},
            "rom_type": inner_rom_type,
            "embedded": embedded,
            "archive_error": archive_error,
            "export_steps": export_steps,
            "export_target": export_target,
            "log": db_rows[0].log if db_rows else "",
            "db_rows": [
                {
                    "game_name": r.game_name,
                    "description": r.description,
                    "status": r.status,
                    "note": r.note,
                    "plan": r.plan or "",
                    "rom_type": r.rom_type,
                }
                for r in db_rows
            ],
        }
