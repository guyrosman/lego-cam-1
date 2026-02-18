from __future__ import annotations

import asyncio
import logging

try:
    from src.lego_cam.config import AppConfig  # type: ignore
except ImportError:
    from lego_cam.config import AppConfig

log = logging.getLogger(__name__)


def _median(values: list[float]) -> float:
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


async def run_sensor_test(config: AppConfig) -> None:
    """
    Developer-only sensor diagnostics:
    - No camera init
    - Prints raw TMF8820 zone results (distance + confidence)
    - Prints summary stats each sample
    """
    poll_hz = max(1, int(config.sensor.poll_hz))
    period = 1.0 / float(poll_hz)

    if config.sensor.simulate:
        raise RuntimeError("sensor_test requires sensor.simulate=false (real TMF8820)")

    try:
        from smbus2 import SMBus  # type: ignore
        from tmf882x import TMF882x, TMF882xException  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "tmf882x-driver is required for sensor_test. Install with:\n"
            "  python3 -m pip install --break-system-packages tmf882x-driver"
        ) from e

    bus = SMBus(1)
    tof = TMF882x(bus, address=0x41)
    log.info("SENSOR_TEST: bus=1 addr=0x41 poll_hz=%s", poll_hz)

    try:
        await asyncio.sleep(0.5)
        tof.enable()
        await asyncio.sleep(0.5)

        # Auto-calibrate in-session if needed (same behavior as your known-good script).
        try:
            if not tof.calibration_ok:
                log.info("SENSOR_TEST: calibration not OK -> calibrating...")
                tof.calibrate()
                log.info("SENSOR_TEST: calibration done")
            else:
                log.info("SENSOR_TEST: calibration OK")
        except Exception as e:
            log.warning("SENSOR_TEST: calibration check/calibrate failed: %s", e)

        n = 0
        while True:
            await asyncio.sleep(period)
            n += 1
            try:
                m = tof.measure()
            except TMF882xException as e:
                log.error("SENSOR_TEST: measure failed: %s", e)
                continue
            except OSError as e:
                log.error("SENSOR_TEST: I2C OS error: %s", e)
                continue

            # Raw per-zone values
            raw = [(r.distance, r.confidence) for r in m.results]
            log.info("SENSOR_TEST #%s: raw zones (distance_mm, confidence)=%s", n, raw)

            dists = [float(d) for (d, c) in raw if d > 0]
            confs = [int(c) for (d, c) in raw if d > 0]
            if not dists:
                log.info("SENSOR_TEST #%s: no distances > 0", n)
                continue

            log.info(
                "SENSOR_TEST #%s: closest=%.1fmm median=%.1fmm farthest=%.1fmm "
                "avg_conf=%.1f zones_with_d=%s n_valid_results=%s",
                n,
                min(dists),
                _median(dists),
                max(dists),
                (sum(confs) / len(confs)) if confs else 0.0,
                len(dists),
                getattr(m, "n_valid_results", "n/a"),
            )
    finally:
        try:
            tof.standby()
        except Exception:
            pass
        try:
            bus.close()
        except Exception:
            pass

