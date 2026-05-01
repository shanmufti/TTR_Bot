"""Logging configuration: rotating file + console handler."""

import functools
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_MAX_LOG_FILES = 10
_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB per file


def _prune_old_logs(log_dir: str) -> None:
    """Keep only the most recent log files."""
    try:
        logs = sorted(Path(log_dir).glob("ttr_bot_*.log"), key=lambda p: p.stat().st_mtime)
        for stale in logs[:-_MAX_LOG_FILES]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


@functools.lru_cache(maxsize=1)
def get_logger() -> logging.Logger:
    """Return the singleton ``ttr_bot`` logger, creating it on first call."""
    logger = logging.getLogger("ttr_bot")
    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(console)

    from ttr_bot.config import settings

    log_dir = settings.LOGS_DIR
    os.makedirs(log_dir, exist_ok=True)

    _prune_old_logs(log_dir)

    log_file = os.path.join(log_dir, f"ttr_bot_{datetime.now():%Y%m%d_%H%M%S}.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_LOG_BYTES,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    return logger


log = get_logger()
