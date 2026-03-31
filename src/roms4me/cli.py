"""CLI entry point using cyclopts."""

import logging
import sys

import cyclopts
import uvicorn
from rich.console import Console

from roms4me.core.logging import setup_logging

app = cyclopts.App(name="roms4me", help="A cross-platform ROM organizer and verifier.")
console = Console(stderr=True)


@app.default
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
    log_level: str = "info",
) -> None:
    """Start the roms4me web server."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    setup_logging(level)

    url = f"http://{host}:{port}"
    console.print()
    console.print("[bold green]roms4me[/bold green] is starting up")
    console.print(f"  [dim]→[/dim] Local:   [link={url}]{url}[/link]")
    if reload:
        console.print("  [dim]→[/dim] Mode:    [yellow]development (reload enabled)[/yellow]")
    else:
        console.print("  [dim]→[/dim] Mode:    production")
    console.print()
    sys.stderr.flush()

    uvicorn.run(
        "roms4me.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


@app.command
def db_reset() -> None:
    """Delete the database. It will be recreated on next start."""
    from roms4me.core.paths import get_data_dir

    db = get_data_dir() / "roms4me.db"
    if db.exists():
        db.unlink()
        console.print(f"[green]Deleted[/green] {db}")
    else:
        console.print(f"[dim]No database found at {db}[/dim]")


@app.command
def db_path() -> None:
    """Print the database file path."""
    from roms4me.core.paths import get_data_dir

    console.print(str(get_data_dir() / "roms4me.db"))


def main() -> None:
    app()
