from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


@dataclass
class Picamera2Recorder:
    """
    Picamera2 video recorder with 30s segmentation.

    Two modes:
    - rotation_mode=rotate: create a new raw H.264 file every segment_seconds by
      switching Picamera2 FileOutput targets. These files typically have a .h264
      extension and can be remuxed to MP4 with ffmpeg.
    - rotation_mode=ffmpeg_segment: pipe raw H.264 to an external ffmpeg segment muxer
      for seamless MP4 segments. (Requires ffmpeg on the system path.)
    """

    output_dir: Path
    width: int
    height: int
    fps: int
    rotation_mode: str
    segment_seconds: int

    _picam2: Any | None = None
    _encoder: Any | None = None
    _running: bool = False
    _rotate_task: asyncio.Task[None] | None = None
    _ffmpeg_proc: subprocess.Popen[bytes] | None = None
    _latest_motion_frame: Any | None = None
    _motion_frame_lock: asyncio.Lock = asyncio.Lock()

    async def start(self) -> None:
        if self._running:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            from picamera2 import Picamera2  # type: ignore
            from picamera2.encoders import H264Encoder  # type: ignore
            from picamera2.outputs import FileOutput  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Picamera2 is required on Raspberry Pi OS. "
                "Install via apt: sudo apt install -y python3-picamera2"
            ) from e

        self._picam2 = Picamera2()

        video_config = self._picam2.create_video_configuration(
            main={"size": (self.width, self.height), "format": "RGB888"},
            controls={"FrameRate": self.fps},
        )
        self._picam2.configure(video_config)

        # Store frames for motion detection (controller will sample while recording).
        self._picam2.pre_callback = self._pre_callback

        self._encoder = H264Encoder(bitrate=10_000_000)

        if self.rotation_mode == "ffmpeg_segment":
            await self._start_ffmpeg_segmenting(FileOutput)
        else:
            await self._start_rotate_outputs(FileOutput)

        self._running = True
        log.info("Camera recording started (mode=%s)", self.rotation_mode)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._rotate_task:
            self._rotate_task.cancel()
            try:
                await self._rotate_task
            except asyncio.CancelledError:
                pass
            self._rotate_task = None

        if self._picam2 is not None:
            try:
                self._picam2.stop_recording()
            except Exception:
                pass
            try:
                self._picam2.stop()
            except Exception:
                pass
            try:
                self._picam2.close()
            except Exception:
                pass

        if self._ffmpeg_proc is not None:
            try:
                self._ffmpeg_proc.terminate()
                self._ffmpeg_proc.wait(timeout=3)
            except Exception:
                pass
            self._ffmpeg_proc = None

        self._picam2 = None
        self._encoder = None
        log.info("Camera recording stopped")

    async def get_motion_frame(self) -> Any | None:
        """
        Returns a recent RGB frame for lightweight motion detection.
        """
        if not self._running:
            return None
        async with self._motion_frame_lock:
            return self._latest_motion_frame

    def _pre_callback(self, request: Any) -> None:
        """
        Called by Picamera2 thread context.
        Keep it lightweight: grab main image array and stash.
        """
        try:
            arr = request.make_array("main")
        except Exception:
            return
        # Avoid blocking the camera thread on asyncio locks; best-effort set.
        self._latest_motion_frame = arr

    async def _start_rotate_outputs(self, FileOutput: Any) -> None:
        assert self._picam2 is not None
        assert self._encoder is not None

        first = self._segment_path()
        out = FileOutput(str(first))
        self._picam2.start()
        self._picam2.start_recording(self._encoder, out)

        async def _rotator() -> None:
            while self._running:
                await asyncio.sleep(self.segment_seconds)
                try:
                    nxt = self._segment_path()
                    self._picam2.switch_output(FileOutput(str(nxt)))
                    log.info("Rotated segment -> %s", nxt.name)
                except Exception:
                    log.exception("Failed rotating output")

        self._rotate_task = asyncio.create_task(_rotator())

    async def _start_ffmpeg_segmenting(self, FileOutput: Any) -> None:
        """
        Pipe raw H264 bitstream to ffmpeg, which splits into mp4 segments.
        """
        assert self._picam2 is not None
        assert self._encoder is not None

        pattern = str(self.output_dir / f"{_utc_stamp()}_%03d.mp4")
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-c",
            "copy",
            "-f",
            "segment",
            "-reset_timestamps",
            "1",
            "-segment_time",
            str(self.segment_seconds),
            pattern,
        ]

        self._ffmpeg_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if self._ffmpeg_proc.stdin is None:
            raise RuntimeError("Failed to open ffmpeg stdin")

        out = FileOutput(self._ffmpeg_proc.stdin)
        self._picam2.start()
        self._picam2.start_recording(self._encoder, out)

    def _segment_path(self) -> Path:
        # In rotate mode we write raw H.264 elementary streams; in ffmpeg_segment
        # mode the external ffmpeg process produces MP4 segments.
        ext = ".mp4" if self.rotation_mode == "ffmpeg_segment" else ".h264"
        return self.output_dir / f"{_utc_stamp()}{ext}"

