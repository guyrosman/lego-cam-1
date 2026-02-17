try:
    from src.lego_cam.sensors.base import BaseSensor  # type: ignore
except ImportError:
    from lego_cam.sensors.base import BaseSensor

__all__ = ["BaseSensor"]

