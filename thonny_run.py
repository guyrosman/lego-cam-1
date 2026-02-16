"""
Thonny-friendly runner.

Usage on Raspberry Pi (Thonny):
1. Open this file and press Run.
2. Edit CONFIG_PATH below to point at your config file.

This avoids needing to install a console script first.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from lego_cam.config import load_config
from lego_cam.logging_setup import setup_logging
from lego_cam.controller import RecordingController
from lego_cam.storage import StorageManager


CONFIG_PATH = Path("config.example.toml")  # change to /etc/lego-cam/config.toml on Pi


async def _run() -> None:
    cfg = load_config(CONFIG_PATH)
    cfg.service.output_dir.mkdir(parents=True, exist_ok=True)
    storage = StorageManager(output_dir=cfg.service.output_dir, min_free_mb=cfg.service.min_free_mb)
    controller = RecordingController(config=cfg, storage=storage)
    await controller.run_forever()


if __name__ == "__main__":
    setup_logging("DEBUG")
    asyncio.run(_run())

