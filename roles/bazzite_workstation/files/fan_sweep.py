#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hold one fan header at a series of duty cycles so a human can listen and rate each one.

WHY A SCRIPT AND NOT A LOOP OF ANSIBLE TASKS. The sweep takes the header to MANUAL mode, which
means the hardware curve is not protecting it for the duration. Ansible cannot guarantee the
restore: a failed task, a lost connection or a Ctrl-C between two tasks leaves the header pinned
at whatever was last written, with nothing to put it back. That is the same hazard the fan
report already names -- a daemon that takes headers to manual and then dies looks exactly like a
BIOS fault and is fixed completely differently. Here the whole sweep is ONE process with the
restore in a `finally` plus signal handlers, so every exit path goes through it.

WHAT IT MEASURES. Two things at once, per step:

  * the RPM the header actually reaches at that duty -- which is how the stall point is found.
    Where the driver declares no `pwm*_min_output` and no `fan*_min`, the duty below
    which a fan stops (and does not restart without a kick) is genuinely unknown until swept.
  * a human noise rating, because "is this quiet?" has no sensor. The sweep holds each step long
    enough to listen, prints what it is doing, and records what you type.

STALL DETECTION IS THE POINT OF THE DWELL. A fan does not stop the instant the duty drops; it
coasts. Reading RPM immediately after a write reports the coast, not the steady state, so a
too-short dwell reports a stalled fan as healthy. The dwell is therefore split: settle, then
measure, and the measurement is the mean of several reads rather than one sample.

THE DEADMAN IS EXTERNAL, because `finally` and signal handlers are not a deadman. They cover a
process that dies POLITELY. They do nothing for SIGKILL, an OOM kill, a kernel panic, the box
losing power, or an SSH connection dropping while this keeps running -- and every one of those
leaves a header in manual mode at whatever duty was last written, with nothing to restore it.

So before touching anything, the sweep arms a DETACHED systemd transient timer that writes the
header back to automatic after a deadline, and disarms it on a clean exit. The timer is not a
child of this process: killing this process does not kill it. If this process vanishes by any
means at all, the header is restored anyway, shortly afterwards. The in-process restore is then
just the fast path for the common case.

INTERACTIVE MODE (--interactive) steps on the human rather than on a clock: it holds each duty
until you have listened and answered, so a rating always describes the speed that was actually
running. `--compare` additionally replays pairs of already-measured steps back to back and asks
which was louder, because "which of these two?" is a question people answer reliably and
"is this a 3 or a 4?" is not.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import signal
import statistics
import subprocess
import sys
import time

# Restore target. Mode 5 is the Super-I/O's own automatic curve -- the state the board was in
# before the sweep, and the safe fallback. NOT mode 0 (full speed): that is loud and is not what
# was there. NOT leaving manual: that is the hazard this whole file exists to avoid.
AUTO_MODE = "5"

# Manual mode. Named because "not manual" is the real success condition for a restore -- see
# Header.restore(), where checking against a remembered value instead of this is a silent guard.
MANUAL_MODE = "1"


class Deadman:
    """A restore that happens even if this process is killed outright.

    Arms a DETACHED systemd transient timer (`systemd-run --on-active=...`) that writes the
    header back to automatic mode after a deadline. Detached is the whole point: the timer is
    not a child of this process, so SIGKILL, an OOM kill, a panic or a dropped connection do not
    take it with them.

    It is re-armed after every step rather than once at the start, so the deadline is always
    measured from the last sign of life. A sweep that hangs mid-step is therefore rescued on the
    same timescale as one that dies, instead of running out a deadline set minutes earlier.
    """

    def __init__(self, header: "Header", seconds: int) -> None:
        self.header = header
        self.seconds = seconds
        self.unit = f"iaac-fan-deadman-hdr{header.index}"
        self.armed = False

    def _run(self, argv: list[str]) -> bool:
        try:
            return (
                subprocess.run(argv, capture_output=True, timeout=15, check=False).returncode == 0
            )
        except (OSError, subprocess.SubprocessError):
            return False

    def arm(self) -> bool:
        """(Re-)arm the timer. Replaces any existing one, so this is safe to call every step."""
        target = self.header.orig_enable or AUTO_MODE
        self.disarm(quiet=True)
        ok = self._run(
            [
                "systemd-run",
                f"--unit={self.unit}",
                f"--on-active={self.seconds}",
                "--timer-property=AccuracySec=1s",
                "--quiet",
                "/bin/sh",
                "-c",
                f"echo {target} > {self.header.enable}",
            ]
        )
        self.armed = self.armed or ok
        return ok

    def disarm(self, quiet: bool = False) -> None:
        # `stop` on the .timer also drops the transient unit. Failure is ignored when quiet,
        # because arm() calls this first and there is usually nothing to stop.
        self._run(["systemctl", "stop", f"{self.unit}.timer"])
        if not quiet:
            self.armed = False


class Header:
    """One pwm channel, with the state needed to put it back exactly as found."""

    def __init__(self, hwmon: pathlib.Path, index: int) -> None:
        self.hwmon = hwmon
        self.index = index
        self.pwm = hwmon / f"pwm{index}"
        self.enable = hwmon / f"pwm{index}_enable"
        self.tach = hwmon / f"fan{index}_input"
        # Captured BEFORE anything is written, so the restore returns the ORIGINAL values rather
        # than an assumed-sane default. If the board was in some other automatic mode, that mode
        # is what comes back.
        self.orig_enable = self._read(self.enable)
        self.orig_pwm = self._read(self.pwm)

    @staticmethod
    def _read(path: pathlib.Path) -> str | None:
        try:
            return path.read_text().strip()
        except OSError:
            return None

    def _write(self, path: pathlib.Path, value: str) -> None:
        path.write_text(f"{value}\n")

    def rpm(self) -> int | None:
        raw = self._read(self.tach)
        return int(raw) if raw and raw.isdigit() else None

    def set_manual(self, duty: int) -> None:
        # Order matters: mode first, then duty. Writing duty while still in an automatic mode is
        # accepted by the driver and then immediately overwritten by the curve on its next
        # evaluation, which presents as "the write did not take" some of the time and not others.
        self._write(self.enable, "1")
        self._write(self.pwm, str(duty))

    def verify_duty(self, duty: int) -> int | None:
        """Read back what actually landed.

        Super-I/O registers can silently CLAMP a written value -- a header with a minimum-output
        floor will accept a write of 20 and hold 60. Reporting the requested duty rather than the
        landed one would put a number in the results table that the hardware never ran, so every
        row records what was read back, not what was asked for.
        """
        raw = self._read(self.pwm)
        return int(raw) if raw and raw.isdigit() else None

    def restore(self, target: str | None = None) -> bool:
        """Put the header back. Returns whether an AUTOMATIC mode was CONFIRMED by read-back.

        Never trusts the write's own success. A restore that silently failed is the worst
        outcome of the whole sweep -- it leaves a fan under no thermal control with a transcript
        that says everything is fine -- so the caller is told whether it was verified, not
        whether it was attempted.

        `target` defaults to the mode captured at construction, which is right for the batch
        sweep (this process put the header into manual, so it knows what it was before).

        IT IS WRONG FOR A RELEASE: a release run
        is a NEW process that finds the header ALREADY in manual from the previous step, so
        `orig_enable` is "1". restore() would write 1, read back 1, and report success -- a
        guard structurally incapable of failing, because it verifies against the broken state
        instead of the correct one, leaving the header in manual while the play prints "released".

        So the result is now checked against what MANUAL CONTROL MEANS rather than against a
        remembered value: mode 1 is never a successful restore, whatever was captured.
        """
        want = target or self.orig_enable or AUTO_MODE
        if want == MANUAL_MODE:
            # Never "restore" to manual. If the captured mode was manual, the header was already
            # stranded when we arrived, and the correct destination is the automatic default.
            want = AUTO_MODE
        try:
            self._write(self.enable, want)
        except OSError:
            return False
        landed = self._read(self.enable)
        # Success requires an AUTOMATIC mode, not merely the mode we asked for.
        return landed == want and landed != MANUAL_MODE


def measure(header: Header, samples: int, interval: float) -> tuple[int | None, int | None]:
    """Mean and spread of several tacho reads. Spread is the tell for an unstable/stalling fan."""
    reads = []
    for _sample in range(samples):
        value = header.rpm()
        if value is not None:
            reads.append(value)
        time.sleep(interval)
    if not reads:
        return None, None
    mean = int(statistics.mean(reads))
    spread = max(reads) - min(reads)
    return mean, spread


def find_hwmon(chip: str) -> pathlib.Path:
    for candidate in sorted(pathlib.Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if (candidate / "name").read_text().strip() == chip:
                return candidate
        except OSError:
            continue
        # hwmonN numbering is NOT stable across reboots, so the chip is located by NAME every
        # run rather than by a remembered path. A stale index would read a different chip
        # entirely, and read it plausibly rather than erroring.
    raise SystemExit(f"fan_sweep: no hwmon chip named {chip!r} -- is nct6775 loaded?")


def run_comparisons(
    header: "Header",
    results: list[dict],
    args: argparse.Namespace,
    deadman: "Deadman | None",
) -> list[dict]:
    """Replay pairs of measured steps back to back and ask which was louder.

    WHY THIS BEATS THE 1-5 RATINGS IT SUPPLEMENTS. An absolute rating drifts: the same fan gets
    a 3 early in a session and a 4 later, because the reference point moves as your ears adapt.
    A DIRECT comparison does not -- "which of these two is louder" is answered reliably and
    consistently, and a set of pairwise answers pins down an ordering that absolute scores only
    approximate.

    Pairs are ADJACENT steps by default, because that is where the answer is actually in doubt:
    100% against 20% tells you nothing you did not know, while 25% against 30% is exactly the
    boundary a floor gets set on.
    """
    pairs: list[dict] = []
    usable = [r for r in results if r.get("rpm")]
    if len(usable) < 2:
        return pairs

    print("\n===== A/B COMPARISON =====", flush=True)
    print("Each pair plays A then B. Answer which was LOUDER.\n", flush=True)

    for first, second in zip(usable, usable[1:]):
        for label, row in (("A", first), ("B", second)):
            duty = int(row["requested_pwm"])
            header.set_manual(duty)
            if deadman is not None:
                deadman.arm()
            print(
                f"  [{label}] {row['requested_pct']}% (rpm was {row['rpm']}) -- listening...",
                flush=True,
            )
            time.sleep(args.settle)

        try:
            answer = input("        louder: a / b / same / q to stop: ").strip().lower()
        except EOFError:
            answer = ""
        if deadman is not None:
            deadman.arm()
        if answer == "q":
            print("        stopping comparisons at your request", flush=True)
            break
        if answer in {"a", "b", "same"}:
            pairs.append(
                {
                    "a_pct": first["requested_pct"],
                    "b_pct": second["requested_pct"],
                    "a_rpm": first["rpm"],
                    "b_rpm": second["rpm"],
                    "louder": answer,
                }
            )
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep one fan header's duty cycle for rating.")
    parser.add_argument("--chip", required=True, help="hwmon chip name carrying the headers")
    parser.add_argument("--header", type=int, required=True, help="pwm channel index")
    parser.add_argument(
        "--steps",
        default="20,25,30,40,50,60,75,100",
        help="duty percentages to hold, in order",
    )
    parser.add_argument(
        "--settle", type=float, default=6.0, help="seconds to settle before measuring"
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--rate",
        action="store_true",
        help="prompt for a 1-5 noise rating at each step (needs a TTY)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help=(
            "hold each duty until you answer, instead of for --settle seconds. "
            "Implies --rate. Needs a TTY."
        ),
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help=(
            "after the sweep, replay pairs of steps back to back and ask which was louder. "
            "Implies --interactive. Needs a TTY."
        ),
    )
    parser.add_argument(
        "--hold",
        type=int,
        default=None,
        metavar="PCT",
        help=(
            "ONE-SHOT: set this duty percent, measure, print the result and EXIT, leaving the "
            "header held at it under the deadman. For a conversational session driven from the "
            "controller: each call is one step, and the operator is asked between calls. "
            "Needs no TTY. Use --release to hand the header back."
        ),
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="ONE-SHOT: return the header to automatic control and disarm the deadman. Ends a --hold session.",
    )
    parser.add_argument(
        "--deadman",
        type=int,
        default=120,
        help=(
            "seconds after the last sign of life before a DETACHED systemd timer restores the "
            "header regardless of what happened to this process. 0 disables (not advised)."
        ),
    )
    parser.add_argument("--json", dest="json_out", help="write results here")
    args = parser.parse_args()

    # --compare implies --interactive implies --rate. Resolved here so every later check reads
    # one flag rather than re-deriving the implication and drifting.
    if args.compare:
        args.interactive = True
    if args.interactive:
        args.rate = True

    # A prompt with no TTY would block forever on a headless run. Refusing up front is better
    # than hanging: the caller gets a usable error instead of a stuck play.
    if args.rate and not (args.hold is not None or args.release) and not sys.stdin.isatty():
        raise SystemExit(
            "fan_sweep: --rate/--interactive/--compare need a terminal, and stdin is not one. "
            "Run this on the machine itself; an Ansible run has no TTY."
        )

    hwmon = find_hwmon(args.chip)
    header = Header(hwmon, args.header)
    if header.orig_enable is None:
        raise SystemExit(f"fan_sweep: header {args.header} has no pwm{args.header}_enable")

    try:
        percents = [int(s) for s in args.steps.split(",") if s.strip()]
    except ValueError:
        raise SystemExit(f"fan_sweep: --steps must be comma-separated integers, got {args.steps!r}")
    if not percents:
        raise SystemExit("fan_sweep: --steps is empty")

    results: list[dict] = []
    comparison_rows: list[dict] = []
    restored = False

    def _bail(signum, _frame):
        # Ctrl-C and SIGTERM must not skip the restore. Raising KeyboardInterrupt here routes
        # both through the same `finally` as a normal exit rather than dying where they land.
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGINT, _bail)
    signal.signal(signal.SIGTERM, _bail)

    # ---- ONE-SHOT MODES -------------------------------------------------------------------
    # These exist so an interactive session can be driven from the CONTROLLER: Ansible sets one
    # duty and returns, the operator is asked in conversation, and the next call sets the next
    # duty. No TTY is involved anywhere, and no process of ours stays alive between steps --
    # which is precisely why the deadman is not optional here. Between two steps the header is
    # in manual with nothing local holding it, so the ONLY thing that will ever put it back if
    # the session is abandoned is the detached timer armed below.
    if args.release:
        rel = Deadman(header, args.deadman if args.deadman > 0 else 60)
        rel.disarm()
        # Explicitly AUTO_MODE: a release run finds the header already in manual, so the
        # captured original is "1" and must not be used as the destination.
        ok = header.restore(AUTO_MODE)
        mode = header._read(header.enable)
        print(f"released: mode={mode} restored={'yes' if ok else 'NO'}", flush=True)
        if not ok:
            print(
                f"*** RESTORE NOT CONFIRMED: pwm{header.index}_enable reads {mode!r}. "
                f"Fix with: echo {header.orig_enable or AUTO_MODE} | sudo tee {header.enable}",
                file=sys.stderr,
                flush=True,
            )
        return 0 if ok else 1

    if args.hold is not None:
        hold_duty = max(0, min(255, round(args.hold * 255 / 100)))
        hold_deadman = Deadman(header, args.deadman) if args.deadman > 0 else None
        if hold_deadman is not None and not hold_deadman.arm():
            raise SystemExit(
                "fan_sweep: could not arm the deadman timer. Refusing to hold a header in "
                "manual mode with nothing to restore it."
            )
        header.set_manual(hold_duty)
        time.sleep(args.settle)
        landed = header.verify_duty(hold_duty)
        rpm, spread = measure(header, args.samples, args.interval)
        clamped = landed is not None and landed != hold_duty
        print(
            json.dumps(
                {
                    "header": args.header,
                    "requested_pct": args.hold,
                    "requested_pwm": hold_duty,
                    "landed_pwm": landed,
                    "landed_pct": round(landed * 100 / 255) if landed is not None else None,
                    "clamped": clamped,
                    "rpm": rpm,
                    "rpm_spread": spread,
                    "stalled": rpm == 0,
                    "deadman_seconds": args.deadman,
                    "original_enable": header.orig_enable,
                }
            ),
            flush=True,
        )
        return 0

    deadman = Deadman(header, args.deadman) if args.deadman > 0 else None
    if deadman is not None and not deadman.arm():
        # Refuse rather than proceed unprotected. The deadman is the only thing covering SIGKILL
        # and a dropped connection; a sweep without it is exactly the hazard this file exists to
        # avoid, so silently continuing would defeat the point.
        raise SystemExit(
            "fan_sweep: could not arm the deadman timer (systemd-run failed). Refusing to take "
            "the header to manual mode without it. Pass --deadman=0 to override deliberately."
        )

    try:
        baseline_rpm, _spread = measure(header, 3, 0.5)
        print(
            f"header {args.header}: starting mode={header.orig_enable} "
            f"pwm={header.orig_pwm} rpm={baseline_rpm}",
            flush=True,
        )
        print(
            "taking the header to MANUAL for the sweep; it returns to automatic at the end.\n",
            flush=True,
        )

        for percent in percents:
            duty = max(0, min(255, round(percent * 255 / 100)))
            header.set_manual(duty)
            if deadman is not None:
                # Re-armed every step, so the deadline always runs from the last sign of life.
                deadman.arm()
            time.sleep(args.settle)
            landed = header.verify_duty(duty)
            rpm, spread = measure(header, args.samples, args.interval)

            landed_pct = round(landed * 100 / 255) if landed is not None else None
            clamped = landed is not None and landed != duty
            note = " (CLAMPED by the chip)" if clamped else ""
            print(
                f"  {percent:>3}% -> pwm {duty:>3} (landed {landed}{note}, ~{landed_pct}%)"
                f"  rpm={rpm}  spread={spread}",
                flush=True,
            )
            if rpm == 0:
                print("        rpm=0 -- STALLED at this duty (or the header is empty)", flush=True)

            row: dict[str, object] = {
                "requested_pct": percent,
                "requested_pwm": duty,
                "landed_pwm": landed,
                "landed_pct": landed_pct,
                "clamped": clamped,
                "rpm": rpm,
                "rpm_spread": spread,
            }

            if args.rate:
                # In interactive mode the header HOLDS this duty until the answer comes back --
                # the fan is still running at exactly the speed being rated, which is the whole
                # point. The deadman keeps covering the wait, and is re-armed after it, so
                # someone walking away mid-sweep is rescued rather than leaving a pinned fan.
                prompt = "        noise 1(silent)-5(loud), s to skip, q to stop: "
                try:
                    answer = input(prompt).strip().lower()
                except EOFError:
                    answer = ""
                if deadman is not None:
                    deadman.arm()
                if answer == "q":
                    print("        stopping early at your request", flush=True)
                    results.append(row)
                    break
                if answer.isdigit() and 1 <= int(answer) <= 5:
                    row["noise"] = int(answer)
                elif answer and answer != "s":
                    row["noise_note"] = answer
            results.append(row)
        if args.compare and len(results) > 1:
            comparisons = run_comparisons(header, results, args, deadman)
            for pair in comparisons:
                print(
                    f"  {pair['a_pct']}% vs {pair['b_pct']}% -> louder: {pair['louder']}",
                    flush=True,
                )
            comparison_rows.extend(comparisons)
    except KeyboardInterrupt as exc:
        print(f"\ninterrupted ({exc}) -- restoring automatic control", flush=True)
    finally:
        restored = header.restore()
        final_mode = header._read(header.enable)
        if deadman is not None:
            if restored:
                # Only disarm once the restore is CONFIRMED. If it could not be confirmed, the
                # timer is deliberately left armed -- it is the last line of defence, and the
                # one case where it is most likely to be needed.
                deadman.disarm()
            else:
                print(
                    f"deadman timer LEFT ARMED: it will write "
                    f"{header.orig_enable or AUTO_MODE} to pwm{header.index}_enable within "
                    f"{args.deadman}s.",
                    file=sys.stderr,
                    flush=True,
                )
        if restored:
            print(
                f"\nheader {args.header} restored to automatic control (mode={final_mode}).",
                flush=True,
            )
        else:
            # Loud, specific, and actionable. A silent failure here is the one outcome that
            # leaves hardware unprotected, so it must never be mistakable for success.
            print(
                f"\n*** RESTORE NOT CONFIRMED on header {args.header}: "
                f"pwm{args.header}_enable reads {final_mode!r}, wanted "
                f"{header.orig_enable or AUTO_MODE!r}. The header may still be in MANUAL mode "
                f"and under no thermal control. Fix with:\n"
                f"    echo {header.orig_enable or AUTO_MODE} | sudo tee {header.enable}",
                file=sys.stderr,
                flush=True,
            )

    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps(
                {
                    "chip": args.chip,
                    "header": args.header,
                    "original_enable": header.orig_enable,
                    "original_pwm": header.orig_pwm,
                    "restored": restored,
                    "steps": results,
                    "comparisons": comparison_rows,
                },
                indent=2,
            )
            + "\n"
        )

    # A sweep whose restore could not be confirmed is a FAILED sweep, whatever it measured.
    return 0 if restored else 1


if __name__ == "__main__":
    sys.exit(main())
