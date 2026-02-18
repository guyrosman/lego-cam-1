from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic

try:
    from src.lego_cam.config import AppConfig  # type: ignore
    from src.lego_cam.motion.vision_motion import VisionMotionDetector  # type: ignore
    from src.lego_cam.sensors.tof_i2c import ToFSensor  # type: ignore
    from src.lego_cam.storage import StorageManager  # type: ignore
except ImportError:
    from lego_cam.config import AppConfig
    from lego_cam.motion.vision_motion import VisionMotionDetector
    from lego_cam.sensors.tof_i2c import ToFSensor
    from lego_cam.storage import StorageManager


log = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"


@dataclass(frozen=True)
class MotionEvent:
    source: str  # sensor|camera
    t_monotonic: float
    score: float = 1.0


class RecordingController:
    """
    Orchestrates sensors, optional vision motion detection, camera recording and storage pruning.
    """

    def __init__(self, config: AppConfig, storage: StorageManager) -> None:
        self._config = config
        self._storage = storage
        self._state: State = State.IDLE
        self._developer_mode: bool = config.service.developer_mode

        self._validate_environment()

        # Backends
        self._sensor = ToFSensor(
            poll_hz=config.sensor.poll_hz,
            simulate=config.sensor.simulate,
            min_confidence=config.sensor.tof_min_confidence,
            calibration_file=config.sensor.tof_calibration_file or "",
            smooth_alpha=config.sensor.tof_smooth_alpha,
            hysteresis_mm=float(config.sensor.tof_hysteresis_mm),
        )
        self._recorder = self._build_recorder()

        vision_enabled = config.motion.enable_vision_motion
        if (
            config.motion.disable_vision_if_radar_or_lidar
            and config.motion.has_radar_or_lidar
        ):
            vision_enabled = False
            log.info("Vision motion disabled because radar/lidar is present (per config)")

        self._vision = VisionMotionDetector(
            enabled=vision_enabled,
            sample_fps=config.motion.vision_motion_fps,
            sensitivity=config.motion.vision_motion_sensitivity,
        )

        self._last_motion_t: float | None = None
        self._last_motion_event: MotionEvent | None = None

    def _validate_environment(self) -> None:
        if self._config.camera.backend != "picamera2":
            raise RuntimeError(
                f"Unsupported camera backend: {self._config.camera.backend}. "
                "Set camera.backend = \"picamera2\" in config."
            )

        try:
            import picamera2  # type: ignore  # noqa: F401
        except Exception as e:
            import sys
            raise RuntimeError(
                "Picamera2 is required but not found in this Python.\n"
                "Current interpreter: %s\n\n"
                "Picamera2 is installed via apt (system Python), not pip.\n"
                "  sudo apt install -y python3-picamera2\n\n"
                "If you run from Thonny: use the interpreter that has picamera2.\n"
                "  Tools → Options → Interpreter → choose\n"
                "  \"The same interpreter which runs Thonny (default)\".\n"
                "Do NOT use the .venv interpreter unless you created it with:\n"
                "  python3 -m venv .venv --system-site-packages"
                % (getattr(sys, "executable", "unknown"))
            ) from e

        if self._config.camera.rotation_mode == "ffmpeg_segment":
            if shutil.which("ffmpeg") is None:
                raise RuntimeError(
                    "ffmpeg not found. Install with:\n"
                    "  sudo apt install -y ffmpeg\n"
                    "Or set camera.rotation_mode = \"rotate\" in config."
                )

        if self._config.motion.enable_vision_motion:
            try:
                import numpy  # type: ignore  # noqa: F401
            except Exception:
                log.warning(
                    "numpy not available; vision motion will be disabled automatically."
                )

        if not self._config.sensor.simulate:
            log.info(
                "Using TMF8820 ToF sensor in hardware mode (sensor.simulate=false)."
            )

    async def run_forever(self) -> None:
        log.info("Controller starting (IDLE)")
        self._state = State.IDLE

        def _log_task_result(task: asyncio.Task[None], name: str) -> None:
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                log.info("Task cancelled: %s", name)
                return
            if exc is not None:
                log.exception("Task failed: %s", name, exc_info=exc)
            else:
                log.warning("Task exited unexpectedly: %s", name)

        async with asyncio.TaskGroup() as tg:
            t1 = tg.create_task(self._sensor_loop())
            t1.add_done_callback(lambda t: _log_task_result(t, "sensor_loop"))
            t2 = tg.create_task(self._camera_motion_loop())
            t2.add_done_callback(lambda t: _log_task_result(t, "camera_motion_loop"))
            t3 = tg.create_task(self._state_loop())
            t3.add_done_callback(lambda t: _log_task_result(t, "state_loop"))
            t_dist = tg.create_task(self._distance_log_loop())
            t_dist.add_done_callback(lambda t: _log_task_result(t, "distance_log_loop"))
            if self._developer_mode:
                t4 = tg.create_task(self._dev_status_loop())
                t4.add_done_callback(lambda t: _log_task_result(t, "dev_status_loop"))

    def _build_recorder(self):
        if self._config.camera.backend != "picamera2":
            raise ValueError(f"Unsupported camera backend: {self._config.camera.backend}")

        try:
            from src.lego_cam.camera.picamera2_recorder import Picamera2Recorder  # type: ignore
        except ImportError:
            from lego_cam.camera.picamera2_recorder import Picamera2Recorder

        return Picamera2Recorder(
            output_dir=self._config.service.output_dir,
            width=self._config.camera.width,
            height=self._config.camera.height,
            fps=self._config.camera.fps,
            rotation_mode=self._config.camera.rotation_mode,
            segment_seconds=self._config.service.segment_seconds,
            developer_mode=self._developer_mode,
        )

    async def _sensor_loop(self) -> None:
        """
        Consume boolean motion events from the ToF sensor backend.

        The sensor is allowed to *start* a recording from IDLE, but once
        recording is running only the camera is allowed to extend the timer.
        """
        async for ev in self._sensor.events():
            if ev:
                await self._on_motion(
                    MotionEvent(source="sensor", t_monotonic=monotonic(), score=1.0)
                )

    async def _camera_motion_loop(self) -> None:
        """
        Vision-based motion is only used while recording (and can be disabled by config).
        """
        while True:
            await asyncio.sleep(0.1)
            if self._state != State.RECORDING:
                continue
            if not self._vision.enabled:
                continue
            frame = await self._recorder.get_motion_frame()
            if frame is None:
                continue
            if self._vision.detect(frame):
                await self._on_motion(MotionEvent(source="camera", t_monotonic=monotonic(), score=1.0))

    async def _distance_log_loop(self) -> None:
        """Log ToF distance to journal every 2s so journalctl always shows it."""
        while True:
            await asyncio.sleep(2.0)
            d = getattr(self._sensor, "debug_distance_mm", None)
            if d is not None:
                log.info("ToF distance_mm=%.1f", d)
            else:
                log.info("ToF distance_mm=n/a")

    async def _state_loop(self) -> None:
        inactivity = self._config.service.inactivity_seconds
        while True:
            await asyncio.sleep(0.2)
            if self._state == State.IDLE:
                continue

            # RECORDING
            if self._last_motion_t is None:
                continue
            if monotonic() - self._last_motion_t >= inactivity:
                log.info("No motion for %ss -> stopping recording", inactivity)
                await self._stop_recording()

    async def _on_motion(self, ev: MotionEvent) -> None:
        # Debouncing: ignore motion events that are too close together (< 0.5s)
        if self._last_motion_t is not None:
            time_since_last = ev.t_monotonic - self._last_motion_t
            if time_since_last < 0.5:
                return  # Ignore rapid-fire events

        self._last_motion_event = ev

        if self._state == State.IDLE:
            # Any source (sensor or camera) can start recording from IDLE.
            self._last_motion_t = ev.t_monotonic
            log.info("Motion detected (%s) -> starting recording", ev.source)
            await self._start_recording()
            return

        # RECORDING:
        # Only camera motion is allowed to extend the inactivity timer.
        if ev.source == "camera":
            self._last_motion_t = ev.t_monotonic
            log.debug("Motion detected (%s) -> reset inactivity timer", ev.source)
        else:
            log.debug(
                "Motion detected (%s) while recording -> ignored for inactivity timer",
                ev.source,
            )

    async def _dev_status_loop(self) -> None:
        """
        Periodically log rich status information for developer mode:
        - distance from sensor (if available)
        - camera/recorder state
        - time since last motion & source
        - basic CPU temperature / load / voltage
        """
        while True:
            await asyncio.sleep(1.0)

            # Time since last motion
            now = monotonic()
            last_motion_age = None
            if self._last_motion_t is not None:
                last_motion_age = now - self._last_motion_t

            last_source = self._last_motion_event.source if self._last_motion_event else None

            # Sensor distance (if backend exposes it)
            distance_mm = getattr(self._sensor, "debug_distance_mm", None)

            # CPU temperature (Raspberry Pi typical path)
            cpu_temp_c: float | None = None
            temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
            try:
                if temp_path.exists():
                    raw = temp_path.read_text().strip()
                    cpu_temp_c = float(raw) / 1000.0
            except Exception:
                cpu_temp_c = None

            # CPU load (1‑minute average)
            cpu_load_1: float | None = None
            try:
                cpu_load_1 = os.getloadavg()[0]
            except (AttributeError, OSError):
                cpu_load_1 = None

            # Core voltage (if vcgencmd is available)
            voltage_v: float | None = None
            try:
                proc = subprocess.run(
                    ["vcgencmd", "measure_volts", "core"],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                    check=False,
                )
                out = proc.stdout.strip()
                # Example: "volt=0.8625V"
                if "volt=" in out and out.endswith("V"):
                    voltage_v = float(out.split("volt=")[1].rstrip("V"))
            except Exception:
                voltage_v = None

            log.info(
                "DEV status | state=%s distance_mm=%s last_motion_age=%.2fs last_source=%s "
                "cpu_temp_c=%s cpu_load_1=%.2f voltage_v=%s",
                self._state.value,
                f"{distance_mm:.1f}" if isinstance(distance_mm, (int, float)) else "n/a",
                last_motion_age if last_motion_age is not None else -1.0,
                last_source or "n/a",
                f"{cpu_temp_c:.1f}" if isinstance(cpu_temp_c, (int, float)) else "n/a",
                cpu_load_1 if cpu_load_1 is not None else -1.0,
                f"{voltage_v:.3f}" if isinstance(voltage_v, (int, float)) else "n/a",
            )

    async def _start_recording(self) -> None:
        self._storage.ensure_free_space()
        try:
            await self._recorder.start()
        except Exception:
            log.exception("Failed to start recorder")
            raise
        self._state = State.RECORDING
        self._last_motion_t = monotonic()

    async def _stop_recording(self) -> None:
        try:
            await self._recorder.stop()
        except Exception:
            log.exception("Error stopping recorder")
        self._storage.ensure_free_space()
        self._state = State.IDLE
        self._last_motion_t = None
        log.info("Controller back to IDLE (camera off)")
