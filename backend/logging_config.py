"""Central logging setup: timestamped console + rotating file output.

Call ``configure_logging()`` once at process start (server.py, cli.py). Every
other module just does ``log = logging.getLogger(__name__)`` and logs
normally - format, level, and file destination are decided here in one place
so every log line (engine retries, job progress, API requests) lands in the
same timestamped stream and the same on-disk file for later debugging.
"""

from __future__ import annotations

import logging
import logging.handlers

from .config import get_websearch_settings

DATA_DIR = get_websearch_settings().data_dir
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "websearch.log"

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


class _SingleLineFormatter(logging.Formatter):
    """Escape CR/LF so user-supplied text (product names, URLs, filenames) can't
    forge extra log lines. Tracebacks are appended after this and stay multi-line."""

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 - stdlib name
        return super().formatMessage(record).replace("\r", "\\r").replace("\n", "\\n")


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = _SingleLineFormatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    # Rotate at 5MB so a long-running server doesn't grow the log file unbounded.
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [console, file_handler]

    # httpx logs one line per HTTP request at INFO - useful but drowns out our
    # own step-by-step logs; keep it, just quieter.
    logging.getLogger("httpx").setLevel(logging.WARNING)
