"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from roms4me.api.config_routes import router as config_router
from roms4me.api.routes import router
from roms4me.core.database import run_migrations
from roms4me.core.paths import ensure_dirs

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from roms4me.core.logging import setup_logging

    setup_logging()
    ensure_dirs()
    run_migrations()

    from roms4me.core.migrate_config import migrate_db_to_toml

    migrate_db_to_toml()

    app = FastAPI(title="roms4me", version="0.1.0")
    app.include_router(router)
    app.include_router(config_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=TEMPLATES_DIR)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html")

    return app
