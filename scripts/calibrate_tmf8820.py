#!/usr/bin/env python3
"""
One-time calibration for the SparkFun TMF8820 ToF sensor.

Run on the Raspberry Pi with the sensor connected (I2C). Conditions:
  - Minimal ambient light
  - No object within 40 cm of the sensor

Do NOT use sudo. Ensure your user can access I2C:
  sudo usermod -aG i2c $USER
  (then log out and back in, or reboot)

Usage:
  python3 scripts/calibrate_tmf8820.py
  python3 scripts/calibrate_tmf8820.py -o /path/to/tmf8820_calibration.bin

Then set in your config.toml:
  [sensor]
  tof_calibration_file = "/path/to/tmf8820_calibration.bin"
"""

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate TMF8820 and save calibration data")
    parser.add_argument(
        "-o", "--output",
        default="tmf8820_calibration.bin",
        help="Output file for calibration bytes (default: tmf8820_calibration.bin)",
    )
    parser.add_argument("-b", "--bus", type=int, default=1, help="I2C bus (default 1)")
    parser.add_argument("-a", "--address", type=int, default=0x41, help="I2C address (default 0x41)")
    args = parser.parse_args()

    try:
        from smbus2 import SMBus  # type: ignore
        from tmf882x import TMF882x, TMF882xException  # type: ignore
    except ImportError as e:
        print("Error: tmf882x-driver is required. Install with:", file=sys.stderr)
        print("  pip install tmf882x-driver", file=sys.stderr)
        return 1

    print("TMF8820 calibration")
    print("  Ensure: no object within 40 cm, minimal ambient light.")
    print("  Bus=%s, address=0x%02X" % (args.bus, args.address))
    print()

    try:
        bus = SMBus(args.bus)
        time.sleep(0.5)  # match working code: delay after opening I2C bus
        tof = TMF882x(bus, address=args.address)
        tof.enable()
        time.sleep(0.5)  # match working code: delay after enable
        print("Running calibration (this may take a few seconds)...")
        cal_bytes = tof.calibrate()
        tof.standby()
        bus.close()
    except TMF882xException as e:
        print("TMF8820 error:", e, file=sys.stderr)
        return 1
    except OSError as e:
        print("I2C error:", e, file=sys.stderr)
        if e.errno == 121:
            print(
                "  (Errno 121 = Remote I/O: sensor not responding. Try: run without sudo; "
                "add user to i2c group: sudo usermod -aG i2c $USER then re-login; "
                "check wiring and power.)",
                file=sys.stderr,
            )
        return 1
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        return 1

    if len(cal_bytes) != 188:
        print("Unexpected calibration size: %s (expected 188)" % len(cal_bytes), file=sys.stderr)
        return 1

    out_path = args.output
    Path(out_path).write_bytes(cal_bytes)
    print("Calibration saved to:", out_path)
    print()
    print("Add to your config.toml:")
    print('  [sensor]')
    print('  tof_calibration_file = "%s"' % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
