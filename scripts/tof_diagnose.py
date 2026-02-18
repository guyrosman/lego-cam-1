#!/usr/bin/env python3
"""
Print raw TMF8820 distance and confidence so you can see what the sensor returns.
Run on the Pi with the sensor connected. No config needed.

  python3 scripts/tof_diagnose.py
  python3 scripts/tof_diagnose.py -n 20   # print 20 samples then exit
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Print TMF8820 raw readings")
    parser.add_argument("-n", "--samples", type=int, default=0, help="Number of samples (0 = forever)")
    parser.add_argument("-b", "--bus", type=int, default=1, help="I2C bus")
    parser.add_argument("-a", "--address", type=int, default=0x41, help="I2C address")
    args = parser.parse_args()

    try:
        from smbus2 import SMBus  # type: ignore
        from tmf882x import TMF882x, TMF882xException  # type: ignore
    except ImportError:
        print("Install: pip install tmf882x-driver", file=sys.stderr)
        return 1

    bus = SMBus(args.bus)
    tof = TMF882x(bus, address=args.address)
    tof.enable()
    print("TMF8820 raw diagnostic (bus=%s addr=0x%02X). Ctrl+C to stop.\n" % (args.bus, args.address))

    n = 0
    try:
        while True:
            m = tof.measure()
            dists = []
            confs = []
            for r in m.results[:9]:  # first 9 = 3x3 grid
                dists.append(r.distance)
                confs.append(r.confidence)
            dists = [d for d in dists if d > 0]
            confs = [c for c in confs if c > 0]
            median_d = sorted(dists)[len(dists) // 2] if dists else 0
            avg_c = sum(confs) / len(confs) if confs else 0
            print(
                "  distance_mm: min=%s median=%s max=%s  confidence: avg=%.1f  (zones with d>0: %s)"
                % (
                    min(dists) if dists else "n/a",
                    median_d,
                    max(dists) if dists else "n/a",
                    avg_c,
                    len(dists),
                )
            )
            n += 1
            if args.samples and n >= args.samples:
                break
    except KeyboardInterrupt:
        pass
    except TMF882xException as e:
        print("TMF8820 error:", e, file=sys.stderr)
        return 1
    finally:
        tof.standby()
        bus.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
