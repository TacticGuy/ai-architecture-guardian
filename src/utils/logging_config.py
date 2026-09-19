"""Consistent, token-safe console and file logging."""
from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_path: str | Path = "logs/pipeline.log", verbose: bool = False) -> logging.Logger:
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pr_dataset")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

