"""
Status LED for developer mode.

Uses BCM GPIO numbering. No-op when GPIO is unavailable (e.g. on non-Pi).
"""

from __future__ import annotations

import asyncio
import logging
log = logging.getLogger(__name__)

_GPIO: object | None = None


def _get_gpio():
    global _GPIO
    if _GPIO is not None:
        return _GPIO
    try:
        import RPi.GPIO as GPIO  # type: ignore
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        _GPIO = GPIO  # type: ignore[assignment]
        return _GPIO
    except Exception:
        return None


async def _led_blink_startup(gpio: object, pin: int, duration_sec: float = 5.0) -> None:
    """Blink on/off for duration_sec (0.5s on, 0.5s off)."""
    import RPi.GPIO as GPIO  # type: ignore
    half = 0.5
    cycles = int(duration_sec / (2 * half))
    for _ in range(cycles):
        GPIO.output(pin, GPIO.HIGH)
        await asyncio.sleep(half)
        GPIO.output(pin, GPIO.LOW)
        await asyncio.sleep(half)


async def _led_blink_tof_fail(gpio: object, pin: int) -> None:
    """5 bursts of 3 blinks, ~3 seconds total."""
    import RPi.GPIO as GPIO  # type: ignore
    blink_on, blink_off = 0.12, 0.08
    burst_pause = 0.25
    for _ in range(5):
        for _ in range(3):
            GPIO.output(pin, GPIO.HIGH)
            await asyncio.sleep(blink_on)
            GPIO.output(pin, GPIO.LOW)
            await asyncio.sleep(blink_off)
        await asyncio.sleep(burst_pause)


async def _led_blink_camera_fail(gpio: object, pin: int) -> None:
    """5 bursts of 5 blinks, ~5 seconds total."""
    import RPi.GPIO as GPIO  # type: ignore
    blink_on, blink_off = 0.1, 0.06
    burst_pause = 0.3
    for _ in range(5):
        for _ in range(5):
            GPIO.output(pin, GPIO.HIGH)
            await asyncio.sleep(blink_on)
            GPIO.output(pin, GPIO.LOW)
            await asyncio.sleep(blink_off)
        await asyncio.sleep(burst_pause)


async def _led_blink_ok(gpio: object, pin: int, duration_sec: float = 3.0) -> None:
    """Slow blink on/off for duration_sec (0.5s on, 0.5s off)."""
    import RPi.GPIO as GPIO  # type: ignore
    half = 0.5
    cycles = int(duration_sec / (2 * half))
    for _ in range(cycles):
        GPIO.output(pin, GPIO.HIGH)
        await asyncio.sleep(half)
        GPIO.output(pin, GPIO.LOW)
        await asyncio.sleep(half)


async def run_developer_led_sequence(
    gpio_pin: int,
    tof_ok: bool,
    camera_ok: bool,
) -> None:
    """
    Run the full developer LED sequence (only when developer_mode and gpio_pin > 0).

    Sequence:
    1. Startup: blink on/off 5 seconds
    2. Then based on health:
       - ToF fail: 5 bursts of 3 blinks (~3s)
       - Camera fail: 5 bursts of 5 blinks (~5s)
       - All OK: slow blink 3 seconds
    """
    g = _get_gpio()
    if g is None or gpio_pin <= 0:
        return
    try:
        import RPi.GPIO as GPIO  # type: ignore
        GPIO.setup(gpio_pin, GPIO.OUT)
        GPIO.output(gpio_pin, GPIO.LOW)

        await _led_blink_startup(g, gpio_pin, 5.0)

        if not tof_ok:
            await _led_blink_tof_fail(g, gpio_pin)
        elif not camera_ok:
            await _led_blink_camera_fail(g, gpio_pin)
        else:
            await _led_blink_ok(g, gpio_pin, 3.0)

        GPIO.output(gpio_pin, GPIO.LOW)
    except Exception as e:
        log.warning("Developer LED failed: %s", e)
