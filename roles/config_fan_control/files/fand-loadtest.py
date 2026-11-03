#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive a component's temperature up and record how the fan control responds.

WHAT THIS VALIDATES. Every threshold in a fan config is a guess until the machine has been hot.
Curves are tuned at idle, where demand sits near zero and nothing is exercised: the gammas, the
ceilings, the damping and the handover between sensors are all untested until something is
actually generating heat.

SAFETY IS THE POINT, NOT AN ADD-ON. This deliberately heats real hardware, so it
is built around ABORT rather than around duration:

  * a per-sensor abort temperature, checked every sample. Reaching it STOPS the load
    immediately -- the test is never worth the component.
  * an abort if a sensor stops being readable. Losing visibility of the thing being heated is
    the worst moment to keep heating it.
  * a hard wall-clock cap, so a stuck load generator cannot run indefinitely.
  * the load is a CHILD PROCESS in its own group, killed on every exit path including a crash
    of this script, so an abandoned run cannot leave the machine cooking.

It records a timeline rather than a verdict: temperature, per-sensor demand, applied duty and
RPM at every sample, so the curve's actual response can be read back afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

HWMON = pathlib.Path("/sys/class/hwmon")


def read_int(path: pathlib.Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def find_chip(name: str, path_contains: str | None = None) -> pathlib.Path | None:
    for hw in sorted(HWMON.glob("hwmon*")):
        try:
            if (hw / "name").read_text().strip() != name:
                continue
        except OSError:
            continue
        if path_contains and path_contains not in str(hw.resolve()):
            continue
        return hw
    return None


def find_temp(hw: pathlib.Path, label: str) -> pathlib.Path | None:
    for lab in sorted(hw.glob("temp*_label")):
        try:
            if lab.read_text().strip() == label:
                return lab.parent / lab.name.replace("_label", "_input")
        except OSError:
            continue
    return None


class Load:
    """A load generator, always in its own process group so it can be killed as a unit."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        # start_new_session puts the child in its own process group: a load generator that
        # forks workers (stress-ng, glmark2) would otherwise leave orphans behind when killed.
        self.proc = subprocess.Popen(
            self.argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


def sample(cfg: dict) -> dict:
    """One observation: every watched sensor, and every watched fan header."""
    row: dict = {"t": round(time.time(), 2), "sensors": {}, "groups": {}}
    for s in cfg["sensors"]:
        hw = find_chip(s["chip"], s.get("path_contains"))
        value = None
        if hw is not None:
            path = find_temp(hw, s["label"]) if s.get("label") else hw / f"temp{s['index']}_input"
            if path is not None:
                raw = read_int(path)
                value = raw / 1000.0 if raw is not None else None
        row["sensors"][s["name"]] = value
    hw = find_chip(cfg["chip"])
    if hw is not None:
        for header in cfg["headers"]:
            row["groups"][str(header)] = {
                "pwm": read_int(hw / f"pwm{header}"),
                "rpm": read_int(hw / f"fan{header}_input"),
                "mode": (
                    (hw / f"pwm{header}_enable").read_text().strip()
                    if (hw / f"pwm{header}_enable").exists()
                    else None
                ),
            }
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Load a component and record the fan response.")
    parser.add_argument("--config", required=True, help="JSON config rendered from inventory")
    parser.add_argument("--duration", type=int, default=180, help="seconds of load")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--out", help="write the timeline here as JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="sample once WITHOUT starting any load -- proves the wiring before heating anything",
    )
    args = parser.parse_args()

    try:
        cfg = json.loads(pathlib.Path(args.config).read_text())
    except (OSError, ValueError) as exc:
        print(f"loadtest: cannot read config: {exc}", file=sys.stderr)
        return 2

    # Resolve everything BEFORE generating heat. A test that starts a load and then discovers it
    # cannot read the temperature is the worst possible ordering.
    first = sample(cfg)
    missing = [n for n, v in first["sensors"].items() if v is None]
    if missing:
        print(
            f"loadtest: REFUSING to start -- unreadable sensor(s): {', '.join(missing)}. "
            f"Heating a component we cannot watch is exactly what the abort logic exists to "
            f"prevent.",
            file=sys.stderr,
        )
        return 2

    print(
        "baseline: " + "  ".join(f"{k}={v:.1f}C" for k, v in first["sensors"].items()), flush=True
    )
    for header, g in first["groups"].items():
        print(f"  hdr{header}: pwm={g['pwm']} rpm={g['rpm']} mode={g['mode']}", flush=True)

    if args.dry_run:
        print("dry run: wiring verified, no load started", flush=True)
        if args.out:
            pathlib.Path(args.out).write_text(
                json.dumps({"dry_run": True, "baseline": first}, indent=2)
            )
        return 0

    abort_at = {a["sensor"]: float(a["celsius"]) for a in cfg.get("abort_above", [])}
    if not abort_at:
        print("loadtest: REFUSING to start -- no abort thresholds declared.", file=sys.stderr)
        return 2

    rows = [first]
    load = Load(cfg["load_command"])
    reason = "completed"
    # A hard wall-clock cap independent of the loop's own accounting: if the load generator
    # wedges, the deadline still ends the run.
    deadline = time.time() + args.duration + 30

    def _bail(signum: int, _frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGINT, _bail)
    signal.signal(signal.SIGTERM, _bail)

    try:
        print(f"\nstarting load: {' '.join(cfg['load_command'])}", flush=True)
        print("abort if: " + ", ".join(f"{k} > {v:g}C" for k, v in abort_at.items()), flush=True)
        load.start()
        started = time.time()

        while True:
            time.sleep(args.interval)
            row = sample(cfg)
            rows.append(row)

            hot = [
                f"{name} {value:.1f}C > {abort_at[name]:g}C"
                for name, value in row["sensors"].items()
                if name in abort_at and value is not None and value > abort_at[name]
            ]
            if hot:
                reason = f"ABORTED: {'; '.join(hot)}"
                print(f"\n*** {reason}", flush=True)
                break

            blind = [n for n, v in row["sensors"].items() if v is None]
            if blind:
                # Losing sight of the component being heated is the worst moment to continue.
                reason = f"ABORTED: sensor(s) became unreadable: {', '.join(blind)}"
                print(f"\n*** {reason}", file=sys.stderr, flush=True)
                break

            elapsed = time.time() - started
            hdr = "  ".join(f"hdr{h}={g['rpm']}rpm/{g['pwm']}" for h, g in row["groups"].items())
            temps = "  ".join(f"{k}={v:.0f}C" for k, v in row["sensors"].items() if v is not None)
            print(f"  {elapsed:5.0f}s  {temps}   {hdr}", flush=True)

            if elapsed >= args.duration:
                break
            if time.time() > deadline:
                reason = "ABORTED: wall-clock deadline exceeded"
                print(f"\n*** {reason}", file=sys.stderr, flush=True)
                break
            if not load.alive():
                reason = "load generator exited early"
                print(f"\n{reason}", flush=True)
                break
    except KeyboardInterrupt as exc:
        reason = f"interrupted ({exc})"
        print(f"\n{reason}", flush=True)
    finally:
        # Every exit path stops the load. An abandoned run must not leave the machine cooking.
        load.stop()
        print("load stopped", flush=True)

    # Cool-down observations: the fall-rate damping is only visible on the way DOWN, and a curve
    # that ramps well but never settles is a real fault this would otherwise miss.
    print("\ncooling down...", flush=True)
    for _sample in range(int(cfg.get("cooldown_samples", 10))):
        time.sleep(args.interval)
        rows.append(sample(cfg))

    peak = {
        name: max(
            (r["sensors"][name] for r in rows if r["sensors"].get(name) is not None),
            default=None,
        )
        for name in first["sensors"]
    }
    print("\npeak temperatures:", flush=True)
    for name, value in peak.items():
        print(f"  {name}: {value:.1f}C" if value is not None else f"  {name}: n/a", flush=True)
    for header in cfg["headers"]:
        rpms = [
            r["groups"][str(header)]["rpm"]
            for r in rows
            if r["groups"].get(str(header), {}).get("rpm") is not None
        ]
        if rpms:
            print(f"  hdr{header}: {min(rpms)}-{max(rpms)} RPM", flush=True)

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({"reason": reason, "peak": peak, "samples": rows}, indent=2) + "\n"
        )
        print(f"\ntimeline written to {args.out}", flush=True)

    return 0 if not reason.startswith("ABORTED") else 1


if __name__ == "__main__":
    sys.exit(main())
