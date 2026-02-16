from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """
    Logging to stdout for systemd/journald capture.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    lvl = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(lvl)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

