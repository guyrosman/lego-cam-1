"""
Status LED for developer mode.

Uses BCM GPIO numbering via gpiozero (works on Pi 5 and avoids "gpio not allocated").
No-op when GPIO is unavailable (e.g. on non-Pi).
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


async def _led_blink_camera_fail(led: object) -> None:
    """5 bursts of 5 blinks, ~5 seconds total."""
    blink_on, blink_off = 0.1, 0.06
    burst_pause = 0.3
    for _ in range(5):
        for _ in range(5):
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
    camera_ok: bool,
) -> None:
    """
    Run the full developer LED sequence (only when developer_mode and gpio_pin > 0).

    Uses gpiozero (works on Pi 5). Sequence:
    1. Startup: blink on/off 5 seconds
    2. Then based on health:
       - ToF fail: 5 bursts of 3 blinks (~3s)
       - Camera fail: 5 bursts of 5 blinks (~5s)
       - All OK: slow blink 3 seconds
    """
    if gpio_pin <= 0:
        return
    led = None
    try:
        from gpiozero import LED  # type: ignore

        led = LED(gpio_pin)
        led.off()

        await _led_blink_startup(led, 5.0)

        if not tof_ok:
            await _led_blink_tof_fail(led)
        elif not camera_ok:
            await _led_blink_camera_fail(led)
        else:
            await _led_blink_ok(led, 3.0)

        led.off()
    except ImportError:
        log.warning(
            "Developer LED: gpiozero not installed. Install with: sudo apt install python3-gpiozero"
        )
    except Exception as e:
        log.warning("Developer LED failed: %s", e)
    finally:
        if led is not None:
            try:
                led.close()
            except Exception:
                pass
