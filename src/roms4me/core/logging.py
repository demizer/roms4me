"""Logging configuration using rich."""

import logging

from rich.logging import RichHandler


def setup_logging(level: int = logging.INFO) -> None:
    """Configure roms4me loggers with Rich handler.

    Sets up the 'roms4me' logger directly instead of root,
    so uvicorn's logging config doesn't overwrite it.
    """
    handler = RichHandler(rich_tracebacks=True)
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))

    app_logger = logging.getLogger("roms4me")
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.setLevel(level)
    app_logger.propagate = False
