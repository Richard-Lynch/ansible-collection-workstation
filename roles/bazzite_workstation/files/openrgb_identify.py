#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Identify which physical devices are on which addressable RGB header.

WHY THIS EXISTS. A motherboard ARGB header cannot tell you what is plugged into it, or how many
LEDs are on the chain. The only way to map header -> hardware is to light them distinctly and
have a human look at the case.

WHAT IT DOES, in three phases:

  1. SOLID      each header a distinct colour, held, so you can say which group is which
  2. CHASE      a single lit LED walks from the first position to the last on ONE header at a
                time, so you can count LEDs per fan and see where one fan ends and the next
                begins — this is what reveals whether the AIO is on the end of a chain
  3. RESTORE    everything back to one colour

IT WRITES TO EVERY DUPLICATE. OpenRGB enumerates the same board twice (an I2C path and a HID
path), and only one of them actually drives the hardware — a test that picks the wrong index
lights nothing and reads as "there is nothing on that header", which is exactly the false
conclusion this script exists to avoid. So it writes to every controller whose name matches,
and lets the physical result speak.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import os
import sys
import time

# THE PROTOCOL CLIENT IS IMPORTED FROM THE DAEMON, NOT REIMPLEMENTED.
#
# A second copy is easy to get wrong in the device-blob layout (omitting the `vendor` string
# shifts every later field and fails with a nonsense buffer demand). The layout is verified by
# landing exactly on each blob's declared length — duplicating it means two things to keep
# correct and one of them silently rotting.
# A second source of truth drifts.
#
# The daemon is installed without a .py extension, so it is loaded by path.

import importlib.util

_DAEMON_PATHS = [
    os.environ.get("IAAC_RGB_DAEMON", ""),
    os.path.expanduser("~/.local/bin/iaac-openrgb-daemon"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "iaac-openrgb-daemon"),
]


def _load_daemon_module():
    for path in _DAEMON_PATHS:
        if path and os.path.exists(path):
            spec = importlib.util.spec_from_loader(
                "iaac_rgb_daemon", importlib.machinery.SourceFileLoader("iaac_rgb_daemon", path)
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise SystemExit(
        "cannot find the RGB daemon to import its protocol client; "
        "looked in: " + ", ".join(p for p in _DAEMON_PATHS if p)
    )


_daemon = _load_daemon_module()
Client = _daemon.OpenRGBClient

# Distinct, unambiguous under case lighting, and nameable without splitting hairs over shade.
HEADER_COLORS = [
    ("RED", (255, 0, 0)),
    ("GREEN", (0, 255, 0)),
    ("BLUE", (0, 80, 255)),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=6742)
    ap.add_argument("--match", required=True, help="device-name substring to drive")
    ap.add_argument("--phase", default="solid", choices=["solid", "chase", "restore"])
    ap.add_argument("--zone", type=int, default=-1, help="chase: which header (0-2), -1 = all")
    ap.add_argument("--step", type=float, default=0.6, help="chase: seconds per LED")
    ap.add_argument(
        "--end-flash",
        action="store_true",
        help="flash the whole chain solid at the end of each pass. OFF by default: "
        "it reads as an extra lit position when you are counting LEDs.",
    )
    ap.add_argument(
        "--loops",
        type=int,
        default=1,
        help="chase: how many times to walk each chain. 0 = forever (until the "
        "process is killed), which is what you want while walking to the case "
        "and back — a single pass is easy to miss.",
    )
    ap.add_argument("--restore-color", default="00A0D0")
    args = ap.parse_args()

    c = Client(args.host, args.port, name="iaac-identify")
    c.connect()
    targets = [d for d in c.devices if args.match.lower() in d["name"].lower()]
    if not targets:
        print(f"no device matching {args.match!r}", file=sys.stderr)
        return 1

    print(
        f"driving {len(targets)} controller(s) named like {args.match!r}: "
        f"{[d['index'] for d in targets]}"
    )
    for d in targets:
        c.set_custom_mode(d["index"])
    time.sleep(0.3)

    if args.phase == "solid":
        for d in targets:
            for zi, n in enumerate(d["zones"]):
                if n == 0:
                    continue
                label, rgb = HEADER_COLORS[zi % len(HEADER_COLORS)]
                c.set_zone_colors(d["index"], zi, [rgb] * n)
        print("\nHEADERS ARE NOW:")
        for zi, (label, _colour) in enumerate(HEADER_COLORS):
            print(f"  header {zi + 1}  ->  {label}")
        print("\nLook at the case and say which group of fans is which colour.")
        print("If a group is dark, that header has nothing on it that can be driven.")

    elif args.phase == "chase":
        zones = range(3) if args.zone < 0 else [args.zone]
        # A chase that runs once is over before you have reached the case. Looping means the
        # pattern is still going when you get there, and repeats so a miscount can be checked.
        forever = args.loops == 0
        loop = 0
        try:
            while forever or loop < args.loops:
                loop += 1
                for zi in zones:
                    n = max((d["zones"][zi] for d in targets if zi < len(d["zones"])), default=0)
                    if n == 0:
                        continue
                    label, rgb = HEADER_COLORS[zi % len(HEADER_COLORS)]
                    print(
                        f"\npass {loop}: header {zi + 1} ({label}), {n} positions, "
                        f"{args.step}s each",
                        flush=True,
                    )
                    for pos in range(n):
                        frame = [(0, 0, 0)] * n
                        frame[pos] = rgb
                        for d in targets:
                            if zi < len(d["zones"]) and d["zones"][zi] >= n:
                                c.set_zone_colors(d["index"], zi, frame)
                        time.sleep(args.step)
                    # End-of-chain marker, OFF by default. It lights the whole chain solid,
                    # which to an observer counting dots reads as one extra position — exactly
                    # the kind of artefact that gets mistaken for a hardware fact. Enable it
                    # only when the question is "where does the chain end", not "how many LEDs".
                    if args.end_flash:
                        for d in targets:
                            if zi < len(d["zones"]) and d["zones"][zi] >= n:
                                c.set_zone_colors(d["index"], zi, [rgb] * n)
                        time.sleep(0.8)
                    for d in targets:
                        if zi < len(d["zones"]):
                            c.set_zone_colors(d["index"], zi, [(0, 0, 0)] * d["zones"][zi])
        except KeyboardInterrupt:
            print("\ninterrupted")
        finally:
            for d in targets:
                for zi, n in enumerate(d["zones"]):
                    if n:
                        c.set_zone_colors(d["index"], zi, [(0, 0, 0)] * n)

    else:  # restore
        rgb = (
            int(args.restore_color[0:2], 16),
            int(args.restore_color[2:4], 16),
            int(args.restore_color[4:6], 16),
        )
        for d in targets:
            for zi, n in enumerate(d["zones"]):
                if n:
                    c.set_zone_colors(d["index"], zi, [rgb] * n)
        print(f"restored to #{args.restore_color}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
