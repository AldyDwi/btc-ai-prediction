import logging
import os
from datetime import datetime
from app.utils.config import config

# ── pastikan folder logs ada ──────────────────────────────────────────────────
os.makedirs(config.LOG_DIR, exist_ok=True)

def get_logger(name: str) -> logging.Logger:
    """
    Buat logger dengan handler file + console.
    Tiap module punya logger sendiri tapi tulis ke file yang sama.
    """
    logger = logging.getLogger(name)

    if logger.handlers:          # hindari duplikat handler
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ── File handler ──────────────────────────────────────
    fh = logging.FileHandler(
        os.path.join(config.LOG_DIR, "training.log"),
        encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # ── Console handler ───────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger