"""
Status LED (optional).

Uses BCM GPIO via gpiozero. Enabled when developer_led_gpio > 0 (independent of developer_mode).
Startup blink + ToF health, then on=recording/motion, off=idle. Does NOT touch the camera.
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
    tof_check_coro,
):
    """
    Run LED sequence (when developer_led_gpio > 0). Does NOT touch the camera.
    Grabs GPIO first (before ToF) to avoid "gpio busy". Runs tof_check_coro
    after startup blink to get ToF status for the result blink.

    Returns the LED object for motion feedback (caller must close when done).
    Returns None if LED failed or gpio_pin <= 0.

    Sequence:
    1. Startup: blink on/off 5 seconds
    2. Await tof_check_coro() -> tof_ok
    3. ToF fail: 5 bursts of 3 blinks; ToF OK: slow blink 3 seconds
    """
    if gpio_pin <= 0:
        return None
    led = None
    try:
        from gpiozero import LED  # type: ignore
    except ImportError:
        log.warning(
            "Developer LED: gpiozero not installed. Install with: sudo apt install python3-gpiozero"
        )
        return None

    for attempt in range(1, 4):
        try:
            await asyncio.sleep(2.0 if attempt > 1 else 0.3)
            led = LED(gpio_pin)
            led.off()
            break
        except Exception as e:
            err = str(e).lower()
            if ("busy" in err or "not allocated" in err or "gpio" in err) and attempt < 3:
                log.debug("Developer LED attempt %s/%s failed (%s), retrying in 2s...", attempt, 3, e)
                continue
            log.warning(
                "Developer LED: GPIO unavailable (%s). "
                "Try developer_led_gpio=17 or another pin, or set to 0 to disable.",
                e,
            )
            return None

    if led is None:
        return None
    try:
        await _led_blink_startup(led, 5.0)
        tof_ok = (await tof_check_coro())[0] if tof_check_coro else True
        if not tof_ok:
            await _led_blink_tof_fail(led)
        else:
            await _led_blink_ok(led, 3.0)
        led.off()
        return led
    except Exception as e:
        log.warning("Developer LED failed during sequence: %s", e)
        try:
            led.close()
        except Exception:
            pass
        return None
