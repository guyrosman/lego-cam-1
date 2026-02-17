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
    # When true, show a live preview window on the attached display (developer mode).
    developer_mode: bool = False

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

        self._encoder = H264Encoder(bitrate=10_000_000)
        
        # Store frames for motion detection (controller will sample while recording).
        # Set callback after encoder is ready but before starting camera
        self._picam2.pre_callback = self._pre_callback

        # Optional on‑screen preview for developer mode.
        if self.developer_mode:
            try:
                from picamera2 import Preview  # type: ignore

                # Try to start a Qt preview (HDMI / desktop); fall back silently if not available.
                try:
                    self._picam2.start_preview(Preview.QT)
                except Exception:
                    try:
                        self._picam2.start_preview()
                    except Exception:
                        pass
                log.info("Developer preview enabled on attached display")
            except Exception:
                # Preview API not available; keep recording headless.
                log.info("Developer preview requested but not available; continuing headless")

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
                if hasattr(self._picam2, 'recording') and self._picam2.recording:
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
            # Small delay to ensure hardware is released
            await asyncio.sleep(0.1)
            # Ensure camera hardware is fully released
            self._picam2 = None

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

        self._picam2.start()

        async def _rotator() -> None:
            segment_num = 0
            while self._running:
                segment_path = self._segment_path()
                if segment_num > 0:
                    # Add segment number to avoid collisions
                    segment_path = self.output_dir / f"{_utc_stamp()}_{segment_num:03d}.h264"
                
                out = FileOutput(str(segment_path))
                self._picam2.start_recording(self._encoder, out)
                log.info("Started segment -> %s", segment_path.name)
                
                await asyncio.sleep(self.segment_seconds)
                
                if self._running:
                    try:
                        self._picam2.stop_recording()
                        log.info("Rotated segment -> %s", segment_path.name)
                    except Exception:
                        log.exception("Failed stopping segment")
                segment_num += 1

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
            "-r",
            str(self.fps),  # Specify frame rate for proper playback
            "-i",
            "pipe:0",
            "-c:v",
            "copy",
            "-f",
            "segment",
            "-reset_timestamps",
            "1",
            "-segment_time",
            str(self.segment_seconds),
            "-movflags",
            "+faststart",  # Enable fast start for web playback
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

