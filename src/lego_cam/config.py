from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServiceConfig:
    output_dir: Path = Path("./videos")
    min_free_mb: int = 1024
    segment_seconds: int = 30
    inactivity_seconds: int = 10


@dataclass(frozen=True)
class CameraConfig:
    backend: str = "picamera2"  # picamera2
    width: int = 1280
    height: int = 720
    fps: int = 30
    codec: str = "h264"
    rotation_mode: str = "rotate"  # rotate|ffmpeg_segment


@dataclass(frozen=True)
class MotionConfig:
    enable_vision_motion: bool = True
    disable_vision_if_radar_or_lidar: bool = True
    has_radar_or_lidar: bool = False
    vision_motion_fps: int = 5
    vision_motion_sensitivity: int = 25


@dataclass(frozen=True)
class SensorConfig:
    backend: str = "tof_i2c"  # tof_i2c
    poll_hz: int = 8
    simulate: bool = False


@dataclass(frozen=True)
class AppConfig:
    service: ServiceConfig = ServiceConfig()
    camera: CameraConfig = CameraConfig()
    motion: MotionConfig = MotionConfig()
    sensor: SensorConfig = SensorConfig()


def _deep_get(d: dict[str, Any], path: list[str], default: Any) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def load_config(path: str | Path) -> AppConfig:
    """
    Load config from TOML or YAML (optional dependency).
    TOML is preferred because it uses stdlib (tomllib) on Python 3.11+.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    ext = p.suffix.lower()
    raw: dict[str, Any]
    if ext in (".toml",):
        import tomllib

        raw = tomllib.loads(p.read_bytes().decode("utf-8"))
    elif ext in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "YAML config requested but PyYAML is not installed. "
                "Install with: pip install -e '.[yaml]'"
            ) from e
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    else:
        raise ValueError(f"Unsupported config extension: {ext}")

    return AppConfig(
        service=ServiceConfig(
            output_dir=Path(_deep_get(raw, ["service", "output_dir"], ServiceConfig().output_dir)),
            min_free_mb=int(_deep_get(raw, ["service", "min_free_mb"], ServiceConfig().min_free_mb)),
            segment_seconds=int(
                _deep_get(raw, ["service", "segment_seconds"], ServiceConfig().segment_seconds)
            ),
            inactivity_seconds=int(
                _deep_get(raw, ["service", "inactivity_seconds"], ServiceConfig().inactivity_seconds)
            ),
        ),
        camera=CameraConfig(
            backend=str(_deep_get(raw, ["camera", "backend"], CameraConfig().backend)),
            width=int(_deep_get(raw, ["camera", "width"], CameraConfig().width)),
            height=int(_deep_get(raw, ["camera", "height"], CameraConfig().height)),
            fps=int(_deep_get(raw, ["camera", "fps"], CameraConfig().fps)),
            codec=str(_deep_get(raw, ["camera", "codec"], CameraConfig().codec)),
            rotation_mode=str(_deep_get(raw, ["camera", "rotation_mode"], CameraConfig().rotation_mode)),
        ),
        motion=MotionConfig(
            enable_vision_motion=bool(
                _deep_get(raw, ["motion", "enable_vision_motion"], MotionConfig().enable_vision_motion)
            ),
            disable_vision_if_radar_or_lidar=bool(
                _deep_get(
                    raw,
                    ["motion", "disable_vision_if_radar_or_lidar"],
                    MotionConfig().disable_vision_if_radar_or_lidar,
                )
            ),
            has_radar_or_lidar=bool(
                _deep_get(raw, ["motion", "has_radar_or_lidar"], MotionConfig().has_radar_or_lidar)
            ),
            vision_motion_fps=int(
                _deep_get(raw, ["motion", "vision_motion_fps"], MotionConfig().vision_motion_fps)
            ),
            vision_motion_sensitivity=int(
                _deep_get(
                    raw, ["motion", "vision_motion_sensitivity"], MotionConfig().vision_motion_sensitivity
                )
            ),
        ),
        sensor=SensorConfig(
            backend=str(_deep_get(raw, ["sensor", "backend"], SensorConfig().backend)),
            poll_hz=int(_deep_get(raw, ["sensor", "poll_hz"], SensorConfig().poll_hz)),
            simulate=bool(_deep_get(raw, ["sensor", "simulate"], SensorConfig().simulate)),
        ),
    )

