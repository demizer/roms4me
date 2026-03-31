"""Centralized scan logger — single source of truth for scan output.

Writes every line to both Python logging (for terminal/systemd/journald)
and an in-memory buffer (for frontend polling and DB persistence).

Supports transient messages (progress bars) that replace each other
in the browser instead of accumulating.
"""

import logging
import threading

log = logging.getLogger("roms4me.scan")


class ScanLog:
    """Thread-safe scan log accumulator with transient message support."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._pending: list[tuple[str, bool]] = []  # (msg, is_transient)
        self._pending_rows: list[dict] = []  # updated row dicts for live grid updates
        self.done: bool = False
        self.done_timestamp: str = ""
        self._lock = threading.Lock()
        self._last_terminal_pct: int = -1

    def info(self, msg: str, transient: bool = False, color: str = "") -> None:
        """Log a scan progress line.

        transient=True means this is a progress update that should
        replace the previous transient message in the browser.
        color can be: green, yellow, red, blue, or empty for default.
        """
        tagged = f"[{color}]{msg}" if color else msg
        with self._lock:
            if not transient:
                self.lines.append(tagged)
                self._last_terminal_pct = -1
            self._pending.append((tagged, transient))
        if not transient:
            log.info(msg)
        else:
            self._log_transient_throttled(msg)

    def _log_transient_throttled(self, msg: str) -> None:
        """Log transient progress to terminal, throttled to every 10%."""
        import re

        match = re.search(r"(\d+)%", msg)
        if not match:
            return
        pct = int(match.group(1))
        bucket = pct // 10 * 10
        if bucket != self._last_terminal_pct:
            self._last_terminal_pct = bucket
            log.info(msg)

    def row_update(self, row: dict) -> None:
        """Queue a row update for live grid refresh."""
        with self._lock:
            self._pending_rows.append(row)

    def warning(self, msg: str) -> None:
        with self._lock:
            self.lines.append(msg)
            self._pending.append((msg, False))
        log.warning(msg)

    def finish(self, timestamp: str) -> None:
        with self._lock:
            self.done = True
            self.done_timestamp = timestamp

    def get_pending(self) -> tuple[list[tuple[str, bool]], bool, str, list[dict]]:
        """Return (pending_messages, is_done, done_timestamp, updated_rows).

        Each message is (text, is_transient).
        updated_rows are row dicts to replace in the grid (keyed by file_name).
        Clears the pending queues.
        """
        with self._lock:
            msgs = list(self._pending)
            self._pending.clear()
            rows = list(self._pending_rows)
            self._pending_rows.clear()
            return msgs, self.done, self.done_timestamp, rows

    def text(self) -> str:
        """Return permanent lines as a single string (for DB storage)."""
        with self._lock:
            return "\n".join(self.lines)


# Global current scan state
current_scan: ScanLog | None = None
scan_running: bool = False
