from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _resolve_level(level_name: str) -> int:
    if not level_name:
        return logging.INFO
    resolved = logging.getLevelName(level_name.upper())
    if isinstance(resolved, int):
        return resolved
    return logging.INFO


def setup_logging(level: str, log_file: Optional[Path] = None) -> None:
    """Configure project wide logging.

    Parameters
    ----------
    level:
        Desired console logging level name. Case-insensitive.
    log_file:
        Optional path to a log file. When provided, a rotating file handler is
        installed with DEBUG level to capture full diagnostic output.
    """

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_level = _resolve_level(level) if level else logging.INFO
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logging.getLogger("aiogram").setLevel(max(logging.INFO, console_level))
