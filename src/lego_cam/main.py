from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

try:
    # When running from source via `python -m src.lego_cam.main`
    from src.lego_cam.config import AppConfig, load_config  # type: ignore
    from src.lego_cam.controller import RecordingController  # type: ignore
    from src.lego_cam.logging_setup import setup_logging  # type: ignore
    from src.lego_cam.storage import StorageManager  # type: ignore
    from src.lego_cam.sensor_test import run_sensor_test  # type: ignore
except ImportError:
    # When installed as a package (console script: lego_cam.main:main)
    from lego_cam.config import AppConfig, load_config
    from lego_cam.controller import RecordingController
    from lego_cam.logging_setup import setup_logging
    from lego_cam.storage import StorageManager
    from lego_cam.sensor_test import run_sensor_test


log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="lego-cam service")
    p.add_argument("--config", required=True, help="Path to config.toml or config.yaml")
    p.add_argument("--log-level", default="INFO", help="DEBUG|INFO|WARNING|ERROR")
    return p.parse_args()


async def _run(config: AppConfig) -> None:
    if config.service.developer_mode and config.service.developer_view.lower() == "sensor_test":
        log.info("Developer sensor_test mode enabled")
        await run_sensor_test(config)
        return

    config.service.output_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageManager(
        output_dir=config.service.output_dir,
        min_free_mb=config.service.min_free_mb,
    )
    controller = RecordingController(config=config, storage=storage)
    await controller.run_forever()


def main() -> None:
    args = _parse_args()
    setup_logging(args.log_level)

    config_path = Path(args.config)
    config = load_config(config_path)
    log.info("Starting lego-cam with config=%s", config_path)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        log.info("Shutdown requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            # On some platforms (e.g. Windows), signal handlers differ.
            signal.signal(sig, lambda *_: _request_stop())

    async def _main_task() -> None:
        runner = asyncio.create_task(_run(config))
        stop_waiter = asyncio.create_task(stop_event.wait())

        # Important: if the runner fails early (e.g. missing dependencies),
        # don't hang forever waiting for SIGINT/SIGTERM.
        done, pending = await asyncio.wait(
            {runner, stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if runner in done:
            stop_waiter.cancel()
            # Propagate exceptions (so the user actually sees what went wrong).
            await runner
            return

        # Stop requested
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass

    try:
        loop.run_until_complete(_main_task())
    finally:
        loop.stop()
        loop.close()


if __name__ == "__main__":
    main()

