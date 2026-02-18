from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from pathlib import Path
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
    min_confidence: int = 5
    calibration_file: str = ""
    smooth_alpha: float = 0.25  # EMA: 0=off, 0.2-0.4=moderate
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
            log.warning(
                "TMF8820 SIMULATION ACTIVE — distance is fake. Set sensor.simulate=false in config for real sensor."
            )
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
            "TMF8820 hardware mode (bus=%s, addr=0x%02X, hysteresis=±40mm, smooth_alpha=%s = raw distance)",
            self.i2c_bus,
            self.i2c_address,
            self.smooth_alpha,
        )

        bus: SMBus | None = None
        tof: TMF882x | None = None
        baseline_mm: Optional[float] = None
        stable_mm: Optional[float] = None

        I2C_RETRIES = 3
        I2C_RETRY_DELAY = 1.5

        def _raise_i2c_hint(e: OSError, after_retries: bool = False) -> None:
            if getattr(e, "errno", None) == 121:
                msg = (
                    "TMF8820 I2C errno 121 (Remote I/O).\n"
                    "  • Power cycle: unplug the TMF8820 (or its 3.3V/GND), wait 5s, plug back in; or reboot the Pi.\n"
                    "  • Close any other program that might use I2C (other Python scripts, calibration script).\n"
                    "  • Check wiring: 3.3V, GND, SDA→GPIO2, SCL→GPIO3; no 5V.\n"
                    "  • If your other TMF8820 script works, run that from the same place (Thonny vs terminal) to compare."
                )
                if after_retries:
                    msg = "TMF8820 I2C errno 121 after %s retries.\n" % I2C_RETRIES + msg
                raise RuntimeError(msg) from e
            raise

        try:
            last_err: OSError | None = None
            for attempt in range(1, I2C_RETRIES + 1):
                if attempt > 1:
                    if bus is not None:
                        try:
                            bus.close()
                        except Exception:
                            pass
                        bus = None
                    log.info("TMF8820 I2C retry %s/%s in %.1fs...", attempt, I2C_RETRIES, I2C_RETRY_DELAY)
                    await asyncio.sleep(I2C_RETRY_DELAY)

                try:
                    bus = SMBus(self.i2c_bus)
                except OSError as e:
                    last_err = e
                    continue

                await asyncio.sleep(1.0)
                tof = TMF882x(bus, address=self.i2c_address)
                try:
                    tof.enable()
                    last_err = None
                    break
                except OSError as e:
                    last_err = e
                    if attempt == I2C_RETRIES:
                        _raise_i2c_hint(e, after_retries=True)
            else:
                if last_err is not None:
                    _raise_i2c_hint(last_err, after_retries=True)
                raise RuntimeError("TMF8820 enable failed")

            await asyncio.sleep(0.5)  # match working code: delay after enable

            if self.calibration_file:
                cal_path = Path(self.calibration_file)
                if cal_path.exists():
                    cal_bytes = cal_path.read_bytes()
                    if len(cal_bytes) == 188:
                        tof.write_calibration(cal_bytes)
                        log.info("TMF8820 loaded calibration from %s", cal_path)
                    else:
                        log.warning(
                            "TMF8820 calibration file %s has wrong size (%s bytes, need 188); skipping",
                            cal_path,
                            len(cal_bytes),
                        )
                else:
                    log.warning("TMF8820 calibration file not found: %s", cal_path)
            else:
                # Match working code: calibrate at runtime if not OK (no file needed)
                if not getattr(tof, "calibration_ok", True):
                    log.info("TMF8820 calibrating...")
                    try:
                        tof.calibrate()
                        log.info("TMF8820 calibration done")
                    except TMF882xException as e:
                        log.warning("TMF8820 calibration failed: %s", e)
                else:
                    log.info("TMF8820 calibration OK (no file)")

            smoothed_mm: Optional[float] = None
            first_sample_logged = False

            while True:
                await asyncio.sleep(period)
                try:
                    m = tof.measure()
                except TMF882xException as e:
                    log.warning("TMF8820 measurement error: %s", e)
                    continue
                except OSError as e:
                    _raise_i2c_hint(e)
                except Exception as e:  # pragma: no cover
                    log.exception("Unexpected TMF8820 error: %s", e)
                    continue

                # Match your working code: accept all distances > 0, use closest (min).
                distances = [float(r.distance) for r in m.results if r.distance > 0]

                if not distances:
                    continue

                raw_mm = min(distances)  # closest object, same as your code

                if self.smooth_alpha > 0 and smoothed_mm is not None:
                    current_mm = self.smooth_alpha * raw_mm + (1.0 - self.smooth_alpha) * smoothed_mm
                    smoothed_mm = current_mm
                else:
                    current_mm = raw_mm
                    smoothed_mm = raw_mm

                self.debug_distance_mm = current_mm

                if not first_sample_logged:
                    first_sample_logged = True
                    log.info(
                        "TMF8820 first sample: distance_mm=%.1f (%s zones with d>0)",
                        current_mm,
                        len(distances),
                    )

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

