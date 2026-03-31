"""API routes for roms4me."""

import logging
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select, func

from roms4me.core.config import add_dat_path as config_add_dat, add_rom_path as config_add_rom
from roms4me.core.config import load_config, remove_dat_path as config_remove_dat
from roms4me.core.config import remove_rom_path as config_remove_rom
from roms4me.core.database import get_session
from roms4me.models.db import PrescanInfo, ScanMeta, ScanResult, System
from roms4me.services.dat_parser import parse_dat_file, scan_dat_dir

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


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
async def refresh() -> dict:
    """Start a pre-scan in a background thread. Returns immediately."""
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
            _do_prescan(scan)
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


def _do_prescan(scan):
    """Run pre-scan: match each ROM directory to DATs using system matcher, then check compatibility."""
    from roms4me.services.prescan import prescan_system
    from roms4me.services.system_matcher import match_system

    scan.info("Starting pre-scan...")

    with get_session() as session:
        dat_paths, rom_paths = _resolve_paths(session)
        systems = {s.id: s.name for s in session.exec(select(System)).all()}

        # Clear old prescan results and scan results
        for r in session.exec(select(PrescanInfo)).all():
            session.delete(r)
        for r in session.exec(select(ScanResult)).all():
            session.delete(r)

        # Clean up stale System rows not referenced by current config
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
                unmatched_count = 0
                for gm in result.games:
                    if gm.unmatched:
                        status = "unmatched"
                        unmatched_count += 1
                    elif gm.matched_file:
                        status = "unverified"
                    else:
                        status = "missing"
                    session.add(ScanResult(
                        system_id=rp.system_id,
                        game_name=gm.game_name,
                        description=gm.description,
                        file_name=gm.matched_file,
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

                for gr in results:
                    session.add(ScanResult(
                        system_id=system.id,
                        game_name=gr.name,
                        description=gr.description,
                        file_name=gr.file_name,
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

        matched_files: dict[str, str] = {}  # file_name -> matched game_name

        for i, filename in enumerate(files):
            pct = round((i + 1) / len(files) * 100)
            scan.info(f"[{i + 1}/{len(files)}] ({pct}%) {filename}", color="blue")

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

            # Run analysis against each DAT
            all_suggestions = []
            for dat in dats:
                analysis = analyze_rom(rom_file, dat, verify_crc=True)
                all_suggestions.extend(analysis.suggestions)

            # Deduplicate and sort
            seen = set()
            unique_suggestions = []
            for s in sorted(all_suggestions, key=lambda x: x.confidence, reverse=True):
                if s.dat_game_name not in seen:
                    seen.add(s.dat_game_name)
                    unique_suggestions.append(s)

            # Log results
            if not unique_suggestions:
                scan.info(f"  No matches found")
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

            # Update DB and build export plan only for CRC matches
            best = unique_suggestions[0]
            export_plan = None
            new_status = None
            plan_label = ""
            if best.crc_match is True:
                new_status = "matched"
                for dat in dats:
                    ep = plan_export(rom_file, best, dat)
                    if ep.steps:
                        export_plan = ep
                        break
                plan_label = "modify" if export_plan and export_plan.steps else "ok"
                if export_plan:
                    scan.info(f"  Export plan → {export_plan.target_name}", color="blue")
                    for step in export_plan.steps:
                        scan.info(f"    {step.name}: {step.description}")

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

    Expects {"files": ["file1.zip", ...], "plan": "delete"}.
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
