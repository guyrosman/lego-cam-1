try:
    from src.lego_cam.motion.vision_motion import VisionMotionDetector  # type: ignore
except ImportError:
    from lego_cam.motion.vision_motion import VisionMotionDetector

__all__ = ["VisionMotionDetector"]

