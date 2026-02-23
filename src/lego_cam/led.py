"""
Status LED for developer mode.

Uses BCM GPIO via gpiozero. Does NOT touch the camera (no Picamera2).
No-op when GPIO fails (e.g. "gpio not allocated" on Pi 5).
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def _led_blink_startup(led: object, duration_sec: float = 5.0) -> None:
    """Blink on/off for duration_sec (0.5s on, 0.5s off)."""
    half = 0.5
    cycles = int(duration_sec / (2 * half))
    for _ in range(cycles):
        led.on()
        await asyncio.sleep(half)
        led.off()
        await asyncio.sleep(half)


async def _led_blink_tof_fail(led: object) -> None:
    """5 bursts of 3 blinks, ~3 seconds total."""
    blink_on, blink_off = 0.12, 0.08
    burst_pause = 0.25
    for _ in range(5):
        for _ in range(3):
            led.on()
            await asyncio.sleep(blink_on)
            led.off()
            await asyncio.sleep(blink_off)
        await asyncio.sleep(burst_pause)


async def _led_blink_ok(led: object, duration_sec: float = 3.0) -> None:
    """Slow blink on/off for duration_sec (0.5s on, 0.5s off)."""
    half = 0.5
    cycles = int(duration_sec / (2 * half))
    for _ in range(cycles):
        led.on()
        await asyncio.sleep(half)
        led.off()
        await asyncio.sleep(half)


async def run_developer_led_sequence(
    gpio_pin: int,
    tof_ok: bool,
) -> None:
    """
    Run LED sequence (developer_mode only). Does NOT touch the camera.

    Sequence:
    1. Startup: blink on/off 5 seconds
    2. ToF fail: 5 bursts of 3 blinks (~3s)
    3. ToF OK: slow blink 3 seconds
    """
    if gpio_pin <= 0:
        return
    led = None
    try:
        await asyncio.sleep(0.5)  # let system settle before GPIO
        from gpiozero import LED  # type: ignore

        led = LED(gpio_pin)
        led.off()

        await _led_blink_startup(led, 5.0)

        if not tof_ok:
            await _led_blink_tof_fail(led)
        else:
            await _led_blink_ok(led, 3.0)

        led.off()
    except ImportError:
        log.warning(
            "Developer LED: gpiozero not installed. Install with: sudo apt install python3-gpiozero"
        )
    except Exception as e:
        err = str(e).lower()
        if "not allocated" in err or "gpio" in err:
            log.warning(
                "Developer LED: GPIO unavailable (%s). "
                "Try a different pin, or ensure no other process uses it.",
                e,
            )
        else:
            log.warning("Developer LED failed: %s", e)
    finally:
        if led is not None:
            try:
                led.close()
            except Exception:
                pass
