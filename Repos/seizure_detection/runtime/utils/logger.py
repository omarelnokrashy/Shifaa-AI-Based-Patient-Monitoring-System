"""utils/logger.py — Centralised logger factory."""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter(
            "[%(asctime)s %(levelname)s %(name)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger
