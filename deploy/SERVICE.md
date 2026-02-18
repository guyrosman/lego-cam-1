# Run lego-cam as a service (no screen needed)

This makes lego-cam start at boot and keep running. You don’t need a monitor or to run Thonny.

## 1. Create the config file

The service will use a single config file (e.g. in `/etc/lego-cam/`).

```bash
sudo mkdir -p /etc/lego-cam
sudo nano /etc/lego-cam/config.toml
```

Paste your working config (same as when you run from Thonny). Important:

- Set `developer_mode = false` for headless (no preview).
- Set `sensor.simulate = false` for real TMF8820.
- Use an **absolute path** for `output_dir`, e.g. `output_dir = "/home/machon/videos"` or `"/var/lib/lego-cam/videos"`.

Save (Ctrl+O, Enter, Ctrl+X).

## 2. Put the service file in place

Copy the unit file and reload systemd:

```bash
sudo cp /home/machon/Downloads/legocam/lego-cam-1/deploy/lego-cam.service /etc/systemd/system/lego-cam.service
sudo systemctl daemon-reload
```

If your project is **not** in `/home/machon/Downloads/legocam/lego-cam-1`, edit the service **before** copying:

```bash
nano /home/machon/Downloads/legocam/lego-cam-1/deploy/lego-cam.service
```

Change:

- `User=` and `Group=` if your Pi user is not `machon`
- `WorkingDirectory=` to the folder that contains your `src` directory (the lego-cam project root)
- `--config ...` in `ExecStart=` if your config is not `/etc/lego-cam/config.toml`

## 3. Enable and start the service

```bash
sudo systemctl enable lego-cam
sudo systemctl start lego-cam
```

After a reboot, lego-cam will start automatically.

## 4. Check that it’s running

```bash
sudo systemctl status lego-cam
```

You should see `active (running)` in green.

## 5. View logs (live)

```bash
journalctl -u lego-cam -f
```

You’ll see the same kind of messages as in Thonny (motion, recording, etc.). Exit with Ctrl+C.

## 6. Stop or disable the service

- Stop until next boot:
  ```bash
  sudo systemctl stop lego-cam
  ```
- Disable so it doesn’t start at boot:
  ```bash
  sudo systemctl disable lego-cam
  ```

## Summary

| Task              | Command |
|-------------------|--------|
| Start now         | `sudo systemctl start lego-cam` |
| Stop              | `sudo systemctl stop lego-cam` |
| Enable at boot    | `sudo systemctl enable lego-cam` |
| Disable at boot   | `sudo systemctl disable lego-cam` |
| Status            | `sudo systemctl status lego-cam` |
| Live logs         | `journalctl -u lego-cam -f` |

No screen or Thonny needed: the service runs in the background and records when the TMF8820 sees motion.
