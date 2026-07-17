"""Rotating application logs and last-resort Qt cleanup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def configure_logging(log_dir: Path) -> logging.Logger:
    """Configure the package logger with a bounded UTF-8 rotating file."""
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "ShiyiDesktopPet.log"
    logger = logging.getLogger("shiyi_desktop_pet")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in tuple(logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            try:
                if Path(handler.baseFilename) == log_path.resolve():
                    return logger
            except (OSError, ValueError):
                pass

    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_048_576,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    return logger


def install_exception_hook(
    logger: logging.Logger,
    *,
    hook_supplier: Callable[[], object | None],
    tray_supplier: Callable[[], object | None],
) -> Callable[[type[BaseException], BaseException, object], None]:
    """Install an exception hook that logs, cleans native UI, and exits Qt."""

    def exception_hook(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: object,
    ) -> None:
        logger.critical(
            "Unhandled application exception",
            exc_info=(exception_type, exception, traceback),
        )
        try:
            hook = hook_supplier()
            if hook is not None:
                hook.stop()
        except Exception:
            logger.exception("Could not stop keyboard hook during exception cleanup")
        try:
            tray = tray_supplier()
            if tray is not None:
                tray.hide()
        except Exception:
            logger.exception("Could not hide tray icon during exception cleanup")
        if QApplication.instance() is not None:
            QTimer.singleShot(0, QApplication.quit)

    sys.excepthook = exception_hook
    return exception_hook
