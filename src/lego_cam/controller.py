from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from time import monotonic

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

        # Backends
        self._sensor = ToFSensor(poll_hz=config.sensor.poll_hz, simulate=config.sensor.simulate)
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

    async def run_forever(self) -> None:
        log.info("Controller starting (IDLE)")
        self._state = State.IDLE

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._sensor_loop())
            tg.create_task(self._camera_motion_loop())
            tg.create_task(self._state_loop())

    def _build_recorder(self):
        if self._config.camera.backend != "picamera2":
            raise ValueError(f"Unsupported camera backend: {self._config.camera.backend}")
        from lego_cam.camera.picamera2_recorder import Picamera2Recorder

        return Picamera2Recorder(
            output_dir=self._config.service.output_dir,
            width=self._config.camera.width,
            height=self._config.camera.height,
            fps=self._config.camera.fps,
            rotation_mode=self._config.camera.rotation_mode,
            segment_seconds=self._config.service.segment_seconds,
        )

    async def _sensor_loop(self) -> None:
        async for ev in self._sensor.events():
            if ev:
                await self._on_motion(MotionEvent(source="sensor", t_monotonic=monotonic(), score=1.0))

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
        self._last_motion_t = ev.t_monotonic
        if self._state == State.IDLE:
            log.info("Motion detected (%s) -> starting recording", ev.source)
            await self._start_recording()
        else:
            # RECORDING: just reset timer
            log.debug("Motion detected (%s) -> reset inactivity timer", ev.source)

    async def _start_recording(self) -> None:
        self._storage.ensure_free_space()
        await self._recorder.start()
        self._state = State.RECORDING
        self._last_motion_t = monotonic()

    async def _stop_recording(self) -> None:
        await self._recorder.stop()
        self._storage.ensure_free_space()
        self._state = State.IDLE
        self._last_motion_t = None
        log.info("Controller back to IDLE (camera off)")

