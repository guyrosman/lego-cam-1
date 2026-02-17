from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import AsyncIterator

try:
    from src.lego_cam.sensors.base import BaseSensor  # type: ignore
except ImportError:
    from lego_cam.sensors.base import BaseSensor


log = logging.getLogger(__name__)


@dataclass
class ToFSensor(BaseSensor):
    """
    Time-of-Flight sensor over I2C.

    This is implemented as:
    - a **simulation mode** (for development/testing without hardware)
    - a **scaffold** for real I2C sensors (exact model/register map TBD)

    When you choose the exact ToF module (e.g. VL53L1X, VL53L0X, etc.),
    we’ll implement proper ranging + presence/motion thresholding here.
    """

    poll_hz: int = 8
    simulate: bool = False
    # For developer-mode status display: most recent distance estimate in mm (if available).
    debug_distance_mm: float | None = None

    async def events(self) -> AsyncIterator[bool]:
        if self.poll_hz <= 0:
            raise ValueError("poll_hz must be > 0")

        period = 1.0 / float(self.poll_hz)

        if self.simulate:
            # Simulation mode with a simple "distance" model and hysteresis.
            #
            # We keep a virtual distance in mm and only emit a motion event
            # when the distance changes by >= 40mm relative to the last stable
            # value. This approximates "only significant movements".
            log.info("ToF sensor simulation enabled (poll_hz=%s, hysteresis=±40mm)", self.poll_hz)
            baseline_mm = 600.0
            stable_mm = baseline_mm
            current_mm = baseline_mm

            while True:
                await asyncio.sleep(period)

                # Small jitter (sensor noise / tiny movements).
                jitter = random.uniform(-5.0, 5.0)
                current_mm = max(50.0, current_mm + jitter)
                self.debug_distance_mm = current_mm

                if abs(current_mm - stable_mm) >= 40.0:
                    log.debug(
                        "Simulated ToF motion event: %.1fmm -> %.1fmm", stable_mm, current_mm
                    )
                    stable_mm = current_mm
                    yield True
                # otherwise: no event
            return

        # Real hardware scaffold
        # NOTE: Avoid adding dependencies until the exact ToF model is selected.
        log.warning("ToF sensor backend is not implemented (set sensor.simulate=true for now)")
        while True:
            await asyncio.sleep(period)
            # no event

