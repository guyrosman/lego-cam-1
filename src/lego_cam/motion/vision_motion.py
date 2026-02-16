from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class VisionMotionDetector:
    """
    Lightweight motion detection using frame differencing.

    Designed to be low CPU:
    - samples at sample_fps (controller controls when to call detect())
    - uses downsampling + absolute difference thresholding
    """

    enabled: bool = True
    sample_fps: int = 5
    sensitivity: int = 25  # higher => less sensitive

    _last_t: float = 0.0
    _prev_small: Any | None = None

    def detect(self, frame_rgb: Any) -> bool:
        """
        frame_rgb is expected to be a numpy ndarray (H, W, 3) RGB.
        Returns True if motion is detected.
        """
        if not self.enabled:
            return False
        if self.sample_fps <= 0:
            return False

        now = time.monotonic()
        if (now - self._last_t) < (1.0 / float(self.sample_fps)):
            return False
        self._last_t = now

        try:
            import numpy as np  # type: ignore
        except Exception:
            # If numpy isn't available, disable detection rather than failing recording.
            return False

        # Downsample aggressively to reduce work.
        small = frame_rgb[::16, ::16, :]
        gray = (0.2989 * small[:, :, 0] + 0.5870 * small[:, :, 1] + 0.1140 * small[:, :, 2]).astype(
            np.float32
        )

        if self._prev_small is None:
            self._prev_small = gray
            return False

        diff = np.abs(gray - self._prev_small)
        self._prev_small = gray

        # Motion score: fraction of pixels above threshold
        thresh = float(self.sensitivity)
        moving = (diff > thresh).mean()
        return moving > 0.02

