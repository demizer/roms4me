# roms4me

> **Alpha** — This project is in early development. Features may change, break, or be incomplete.

A ROM collection organizer, verifier and bulk renamer. Matches your ROM files against No-Intro DAT databases using CRC32 checksums, identifies mismatches, strips copier headers, and plans exports to get your collection into shape.

## Features

* Supports Linux, macos, and Windows
- **CRC verification** — verify ROMs against DAT databases, detect bad dumps and mismatches
- **Analyzer pipeline** — heuristic matching for unidentified ROMs: direct CRC lookup, copier header stripping, region mapping, fuzzy name matching
- **Export planner** — plans file transformations: header removal, renaming, repackaging
- **Web UI** — responsive browser interface with filterable/sortable data grid, real-time analysis progress, context menus, and system management
- **Multi-system** — scan and manage multiple platforms simultaneously
- **Pre-scan** — quick compatibility check between ROM directories and DAT files before full verification

## Quick Start

```bash
git clone https://github.com/demizer/roms4me.git
cd roms4me
uv sync
just serve
```

Open http://127.0.0.1:8000 in your browser.

1. Click **Settings** and add your ROM directory paths
2. Add your DAT file directory paths (No-Intro format)
3. Click **Sync** to scan and match ROMs against DATs
4. Select a system in the sidebar to view results
5. Select ROMs and click **Analyze** for CRC verification

## ROM Directory Naming

See the [ROM Directory Format](docs/rom-directory-format.md) documentation for details and the full system name mapping.

## Data Storage

Application data is stored in the platform-specific user data directory:

| Platform | Path |
|----------|------|
| Linux | `~/.local/share/roms4me/` |
| macOS | `~/Library/Application Support/roms4me/` |
| Windows | `%APPDATA%/roms4me/` |


## License

MIT
