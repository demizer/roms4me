# Contributing to roms4me

This app was largely created using Claude Code on Arch Linux by the maintainer.

## What's accepted

**Bug fixes and test coverage improvements** — open a merge request directly.

**Feature requests** — must go through this process:

1. Start a discussion on [GitHub Discussions](https://github.com/demizer/roms4me/discussions) describing the feature and your use case
2. If approved, submit a merge request with the implementation

Feature MRs must include regression tests. Features that don't fit the maintainer's workflow will not be merged.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)

## Setup

```bash
git clone https://github.com/demizer/roms4me.git
cd roms4me
uv sync
```

## Development

```bash
# Development server with auto-reload
just dev

# Run tests
just test

# Lint and format
just lint
just fmt

# Database operations
roms4me db-path
roms4me db-reset
```

## Tech Stack

- **Backend** — Python, FastAPI, SQLModel (SQLite), Alembic, Uvicorn
- **Frontend** — Vanilla JS, PicoCSS
- **CLI** — Cyclopts, Rich
- **Testing** — pytest, Playwright (Firefox)
