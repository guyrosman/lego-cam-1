try:
    from src.lego_cam.camera.picamera2_recorder import Picamera2Recorder  # type: ignore
except ImportError:
    from lego_cam.camera.picamera2_recorder import Picamera2Recorder

__all__ = ["Picamera2Recorder"]

