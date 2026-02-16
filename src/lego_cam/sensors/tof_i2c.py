from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import AsyncIterator

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

    async def events(self) -> AsyncIterator[bool]:
        if self.poll_hz <= 0:
            raise ValueError("poll_hz must be > 0")

        period = 1.0 / float(self.poll_hz)

        if self.simulate:
            while True:
                await asyncio.sleep(period)
                # 5% chance per tick to simulate presence/motion
                if random.random() < 0.05:
                    log.debug("Simulated ToF motion event")
                    yield True
                # otherwise: no event
            return

        # Real hardware scaffold
        # NOTE: Avoid adding dependencies until the exact ToF model is selected.
        log.warning("ToF sensor backend is not implemented (set sensor.simulate=true for now)")
        while True:
            await asyncio.sleep(period)
            # no event

