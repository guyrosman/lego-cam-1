# lego-cam

Production-oriented, low-power, sensor-triggered recording service for Raspberry Pi 5 (Python 3.11), using **Picamera2** and a pluggable sensor architecture.

## Behavior
- **IDLE**: sensors on, camera off, low CPU usage.
- **Trigger**: sensor motion/presence turns camera on and starts recording immediately.
- **Recording**:
  - Saves video in **30s segments** (each file is ≤30 seconds).
  - Motion events reset a **10 second** inactivity timer.
- **Stop**: when there is **10s of no motion**, recording stops, camera turns off, returns to IDLE.
- **Storage pruning**: if disk space is low, deletes the **oldest** videos first.

## Install (Raspberry Pi OS)
Picamera2 is normally installed via apt:

```bash
sudo apt update
sudo apt install -y python3-picamera2 ffmpeg
```

Project install (editable):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you want YAML config support:

```bash
pip install -e ".[yaml]"
```

## Configuration
The service loads TOML by default. Example:

```toml
[service]
output_dir = "/var/lib/lego-cam/videos"
min_free_mb = 1024
segment_seconds = 30
inactivity_seconds = 10

[camera]
backend = "picamera2"
width = 1280
height = 720
fps = 30
codec = "h264"
rotation_mode = "ffmpeg_segment"  # ffmpeg_segment|rotate

[motion]
enable_vision_motion = true
has_radar_or_lidar = false
disable_vision_if_radar_or_lidar = true
vision_motion_fps = 5
vision_motion_sensitivity = 25

[sensor]
backend = "tof_i2c"
poll_hz = 8
simulate = true
```

Run:

```bash
lego-cam --config config.toml
```

## Testing in Thonny (Raspberry Pi)
If you use **Thonny**, you can run without installing the console script:
- Open `[thonny_run.py](thonny_run.py)` and press **Run**.
- Point `CONFIG_PATH` at your config file.

## Run as a service (no screen)

To run lego-cam at boot without a monitor or Thonny, use the systemd service:

1. **Setup:** [deploy/SERVICE.md](deploy/SERVICE.md) — create config, install the unit, enable and start.
2. **Unit file:** [deploy/lego-cam.service](deploy/lego-cam.service) — edit `User`, `WorkingDirectory`, and `--config` path if needed.

Quick version (after editing the service file for your paths and user):

```bash
sudo mkdir -p /etc/lego-cam
# put your config.toml in /etc/lego-cam/
sudo cp deploy/lego-cam.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lego-cam
journalctl -u lego-cam -f   # live logs
```

