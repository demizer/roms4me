# Contributing to roms4me

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
