# roms4me

> **Alpha** — This project is in early development. Features may change, break, or be incomplete.

A ROM collection organizer and verifier. Matches your ROM files against No-Intro DAT databases using CRC32 checksums, identifies mismatches, strips copier headers, and plans exports to get your collection into shape.

## Features

- **CRC verification** — verify ROMs against DAT databases, detect bad dumps and mismatches
- **Analyzer pipeline** — heuristic matching for unidentified ROMs: direct CRC lookup, copier header stripping (SNES/NES/Lynx/7800), region mapping, fuzzy name matching
- **Export planner** — plans file transformations: header removal, renaming, repackaging
- **Web UI** — responsive browser interface with filterable/sortable data grid, real-time analysis progress, context menus, and system management
- **Multi-system** — scan and manage multiple platforms simultaneously
- **Pre-scan** — quick compatibility check between ROM directories and DAT files before full verification

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just) (optional, for task running)

## Quick Start

```bash
git clone https://github.com/demuredemeanor/roms4me.git
cd roms4me
uv sync
just dev
```

Open http://127.0.0.1:8000 in your browser.

1. Click **Settings** and add your ROM directory paths
2. Add your DAT file directory paths (No-Intro format)
3. Click **Sync** to scan and match ROMs against DATs
4. Select a system in the sidebar to view results
5. Select ROMs and click **Analyze** for CRC verification

## Usage

```bash
# Development server with auto-reload
just dev

# Production server
just serve

# Run tests
just test

# Lint and format
just lint
just fmt

# Database operations
roms4me db-path
roms4me db-reset
```

## ROM Directory Naming

ROM directories should follow the `Company - System` convention to enable automatic DAT matching:

```
ROMs/
  Nintendo - SNES/
  Nintendo - NES/
  Sega - Genesis/
```

See [rom-directory-format](docs/rom-directory-format.md) for the full system name mapping.

## Tech Stack

- **Backend** — Python, FastAPI, SQLModel (SQLite), Alembic, Uvicorn
- **Frontend** — Vanilla JS, PicoCSS
- **CLI** — Cyclopts, Rich
- **Testing** — pytest, Playwright (Firefox)

## Data Storage

Application data is stored in the platform-specific user data directory:

| Platform | Path |
|----------|------|
| Linux | `~/.local/share/roms4me/` |
| macOS | `~/Library/Application Support/roms4me/` |
| Windows | `%APPDATA%/roms4me/` |

## License

MIT
