from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import AsyncIterator, Optional

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
    i2c_bus: int = 1
    i2c_address: int = 0x41
    # For developer-mode status display: most recent distance estimate in mm (if available).
    debug_distance_mm: Optional[float] = None

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

        # Real hardware path: SparkFun TMF8820 via tmf882x-driver.
        try:
            from smbus2 import SMBus  # type: ignore
            from tmf882x import TMF882x, TMF882xException  # type: ignore
        except Exception:  # pragma: no cover - import-time failure on non-Pi dev machines
            log.error(
                "TMF8820 backend requested but tmf882x-driver or smbus2 is not installed. "
                "Install with: pip install tmf882x-driver  "
                "or set sensor.simulate=true in the config."
            )
            while True:
                await asyncio.sleep(period)
                # No events; configuration is invalid.

        log.info(
            "TMF8820 hardware mode enabled (bus=%s, addr=0x%02X, hysteresis=±40mm)",
            self.i2c_bus,
            self.i2c_address,
        )

        bus: SMBus | None = None
        tof: TMF882x | None = None
        baseline_mm: Optional[float] = None
        stable_mm: Optional[float] = None

        try:
            bus = SMBus(self.i2c_bus)
            tof = TMF882x(bus, address=self.i2c_address)
            tof.enable()

            while True:
                await asyncio.sleep(period)
                try:
                    m = tof.measure()
                except TMF882xException as e:
                    log.warning("TMF8820 measurement error: %s", e)
                    continue
                except Exception as e:  # pragma: no cover
                    log.exception("Unexpected TMF8820 error: %s", e)
                    continue

                # Collapse the measurement grid to a single representative distance.
                # Only use zones with sufficient confidence (low confidence = noise/wrong).
                # Use median of valid distances to avoid one bad zone dominating.
                MIN_CONFIDENCE = 10  # 0–255; below this we ignore the zone
                distances: list[float] = []
                try:
                    for dist_row, conf_row in zip(
                        m.primary_grid,
                        m.primary_grid_confidence,
                    ):
                        for d, c in zip(dist_row, conf_row):
                            if d > 0 and c >= MIN_CONFIDENCE:
                                distances.append(float(d))
                except Exception:
                    continue

                if not distances:
                    # No zones above confidence threshold; keep previous value.
                    continue

                # Median is more stable than min when one zone is noisy
                distances.sort()
                mid = len(distances) // 2
                current_mm = (
                    distances[mid]
                    if len(distances) % 2
                    else (distances[mid - 1] + distances[mid]) / 2.0
                )
                self.debug_distance_mm = current_mm

                if baseline_mm is None:
                    baseline_mm = current_mm
                    stable_mm = current_mm
                    continue

                if stable_mm is None:
                    stable_mm = current_mm
                    continue

                if abs(current_mm - stable_mm) >= 40.0:
                    log.debug(
                        "TMF8820 motion event: %.1fmm -> %.1fmm", stable_mm, current_mm
                    )
                    stable_mm = current_mm
                    yield True
                # otherwise: no event
        finally:
            try:
                if tof is not None:
                    try:
                        tof.standby()
                    except Exception:
                        pass
            finally:
                if bus is not None:
                    try:
                        bus.close()
                    except Exception:
                        pass

