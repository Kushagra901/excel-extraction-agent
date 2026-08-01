"""Central logging configuration -- console (INFO+) and file (DEBUG+)."""

from __future__ import annotations

import logging
from pathlib import Path

_LOGGER_NAME = "excel_agent"


def setup_logging(log_path: Path, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)

    # Properly close any handlers left over from a previous run before
    # detaching them. `logger.handlers.clear()` alone only detaches the
    # handler objects -- it does NOT close their underlying file
    # descriptors. On POSIX this leak is invisible because the OS allows
    # deleting/renaming a file that still has an open handle. On Windows
    # it is not allowed, so a leaked FileHandler will cause a
    # PermissionError the next time something tries to remove or
    # overwrite that log file (e.g. tempfile.TemporaryDirectory cleanup).
    close_logging()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def close_logging() -> None:
    """Flush and close every handler on the excel_agent logger, then
    detach them. Must be called once a run's output has been fully
    written, so the log file's OS-level handle is released -- this is
    what allows Windows to delete/rename the file afterward (e.g. when a
    test's tempfile.TemporaryDirectory tears itself down)."""
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)

