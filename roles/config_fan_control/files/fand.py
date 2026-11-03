#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fan control by normalised per-component demand.

Each sensor is normalised to a 0-100 demand against ITS OWN floor/ceiling/gamma; each fan group
follows the MAXIMUM demand across the sensors it cares about. Normalisation is what makes that
maximum meaningful -- 70 C is alarming on an NVMe and unremarkable on an X3D, so a maximum over
raw temperatures would be nonsense.

WHY THIS EXISTS AT ALL. The Super-I/O chip can only steer its own curves off its own temp1-13
channels; amdgpu, nvme and k10temp are separate chips, invisible to it. Anything the chip CAN do
belongs in the chip's curve, where no userspace process sits in the thermal path. This daemon
exists only for what the hardware cannot express.

CONFIG IS DATA, NOT CODE. Everything machine-specific -- which sensors exist, their thresholds,
which headers exist, what each drives, which are pumps -- arrives as JSON rendered from
inventory. A second machine needs an inventory block and no change here.

"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import pathlib
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Any

HWMON_ROOT = pathlib.Path("/sys/class/hwmon")
AUTO_MODE = "5"
MANUAL_MODE = "1"

log = logging.getLogger("fand")


class ConfigError(Exception):
    """Configuration is wrong in a way that must stop the daemon starting."""


# ---------------------------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------------------------


@dataclass
class Sensor:
    """One temperature input, resolved to a real sysfs file at startup.

    RESOLVED BY chip name + predicate, NEVER by a remembered path. Two facts force this:
    hwmonN numbering is not stable across reboots (a daemon holding hwmon1/temp2_input reads
    something else after a re-enumeration -- and reads it PLAUSIBLY rather than erroring), and
    this class of board can carry two chips of the same name (a discrete GPU and an iGPU both
    register as `amdgpu`), so a name alone is ambiguous.
    """

    name: str
    chip: str
    floor: float
    ceiling: float
    gamma: float = 1.0
    label: str | None = None
    index: int | None = None
    path_contains: str | None = None

    path: pathlib.Path | None = field(default=None, init=False)
    hw_crit: float | None = field(default=None, init=False)
    last_good: float | None = field(default=None, init=False)
    fail_count: int = field(default=0, init=False)

    def resolve(self) -> None:
        """Find this sensor's sysfs file, or raise. Never guesses."""
        candidates = []
        for hw in sorted(HWMON_ROOT.glob("hwmon*")):
            try:
                if (hw / "name").read_text().strip() != self.chip:
                    continue
            except OSError:
                continue
            if self.path_contains and self.path_contains not in str(hw.resolve()):
                continue
            candidates.append(hw)

        if not candidates:
            raise ConfigError(
                f"sensor {self.name!r}: no hwmon chip named {self.chip!r}"
                + (f" with {self.path_contains!r} in its path" if self.path_contains else "")
            )
        if len(candidates) > 1 and not self.path_contains:
            paths = ", ".join(str(c.resolve()) for c in candidates)
            raise ConfigError(
                f"sensor {self.name!r}: {len(candidates)} chips named {self.chip!r} ({paths}). "
                f"Add path_contains to disambiguate -- picking one arbitrarily could silently "
                f"read the wrong device."
            )

        hw = candidates[0]
        if self.index is not None:
            found = hw / f"temp{self.index}_input"
            if not found.exists():
                raise ConfigError(f"sensor {self.name!r}: {found} does not exist")
        elif self.label is not None:
            found = None
            for lab in sorted(hw.glob("temp*_label")):
                try:
                    if lab.read_text().strip() == self.label:
                        found = lab.parent / lab.name.replace("_label", "_input")
                        break
                except OSError:
                    continue
            if found is None:
                have = []
                for lab in sorted(hw.glob("temp*_label")):
                    try:
                        have.append(lab.read_text().strip())
                    except OSError:
                        pass
                raise ConfigError(
                    f"sensor {self.name!r}: no channel labelled {self.label!r} on {self.chip} "
                    f"(have: {', '.join(have) or 'no labels'})"
                )
        else:
            raise ConfigError(f"sensor {self.name!r}: needs either `label` or `index`")

        self.path = found
        self._check_against_hardware_limits()

    def _check_against_hardware_limits(self) -> None:
        """Assert the declared ceiling against the limits the hardware itself declares.

        A ceiling above the chip's own critical temperature is a configuration error, not a
        preference: it would mean the fans do not reach full speed until after the component is
        already past the point its vendor calls critical.
        """
        assert self.path is not None
        stem = str(self.path).replace("_input", "")
        for attr in ("crit", "emergency", "max"):
            try:
                value = int(pathlib.Path(f"{stem}_{attr}").read_text().strip()) / 1000.0
            except (OSError, ValueError):
                continue
            # Some drivers park an unset limit at an absurd value (some NVMe drives report
            # max=65261850). Treat anything non-physical as undeclared rather than trusting it.
            if not (0 < value < 200):
                continue
            self.hw_crit = value if self.hw_crit is None else min(self.hw_crit, value)

        if self.hw_crit is not None and self.ceiling > self.hw_crit:
            raise ConfigError(
                f"sensor {self.name!r}: ceiling {self.ceiling}C is above the hardware's own "
                f"declared limit {self.hw_crit}C -- the fans would not reach full speed until "
                f"after the component is past critical."
            )

    def read(self) -> float | None:
        """Current temperature in C, or None if unreadable."""
        if self.path is None:
            return None
        try:
            value = int(self.path.read_text().strip()) / 1000.0
        except (OSError, ValueError):
            self.fail_count += 1
            return None
        self.fail_count = 0
        self.last_good = value
        return value

    def demand(self, temp: float) -> float:
        """Normalise a temperature to 0-100 demand against this sensor's own thresholds."""
        if self.ceiling <= self.floor:
            return 100.0
        frac = (temp - self.floor) / (self.ceiling - self.floor)
        frac = max(0.0, min(1.0, frac))
        return (frac**self.gamma) * 100.0


# ---------------------------------------------------------------------------------------------
# Fan groups
# ---------------------------------------------------------------------------------------------


@dataclass
class Group:
    """One PWM header, the fans on it, and the sensors it cares about."""

    name: str
    header: int
    chip: str
    sensors: list[str]
    pwm_min: int
    pwm_max: int = 255
    note: str = ""

    hwmon: pathlib.Path | None = field(default=None, init=False)
    orig_enable: str | None = field(default=None, init=False)
    applied: int | None = field(default=None, init=False)
    smoothed: float = field(default=0.0, init=False)
    driver: str = field(default="", init=False)
    in_failsafe: bool = field(default=False, init=False)

    def resolve(self) -> None:
        for hw in sorted(HWMON_ROOT.glob("hwmon*")):
            try:
                if (hw / "name").read_text().strip() == self.chip:
                    self.hwmon = hw
                    break
            except OSError:
                continue
        if self.hwmon is None:
            raise ConfigError(f"group {self.name!r}: no hwmon chip named {self.chip!r}")
        if not (self.hwmon / f"pwm{self.header}_enable").exists():
            raise ConfigError(
                f"group {self.name!r}: header {self.header} has no pwm{self.header}_enable "
                f"on {self.chip}"
            )
        self.orig_enable = self._read(f"pwm{self.header}_enable")

    def _read(self, leaf: str) -> str | None:
        assert self.hwmon is not None
        try:
            return (self.hwmon / leaf).read_text().strip()
        except OSError:
            return None

    def _write(self, leaf: str, value: str) -> bool:
        assert self.hwmon is not None
        try:
            (self.hwmon / leaf).write_text(f"{value}\n")
        except OSError as exc:
            log.error("group %s: write %s=%s failed: %s", self.name, leaf, value, exc)
            return False
        return True

    def rpm(self) -> int | None:
        raw = self._read(f"fan{self.header}_input")
        return int(raw) if raw and raw.isdigit() else None

    def apply(self, duty: int) -> bool:
        """Set duty, confirming by read-back. Never trusts the write's own success."""
        if self._read(f"pwm{self.header}_enable") != MANUAL_MODE:
            if not self._write(f"pwm{self.header}_enable", MANUAL_MODE):
                return False
        if not self._write(f"pwm{self.header}", str(duty)):
            return False
        landed = self._read(f"pwm{self.header}")
        if landed is None or not landed.isdigit():
            return False
        # Super-I/O registers can silently CLAMP, so record what actually landed rather than
        # what was asked for -- a reported duty the hardware never ran is worse than none.
        self.applied = int(landed)
        return True

    def release(self) -> bool:
        """Hand the header back to the hardware curve. Confirmed by read-back.

        Never restores to MANUAL_MODE even if that is what was captured at startup: a header
        found in manual was already stranded, and the correct destination is automatic. (Restoring
        the captured MANUAL leaves a header stranded while reporting success -- a guard that
        verifies against the broken state.)
        """
        want = self.orig_enable or AUTO_MODE
        if want == MANUAL_MODE:
            want = AUTO_MODE
        self._write(f"pwm{self.header}_enable", want)
        landed = self._read(f"pwm{self.header}_enable")
        ok = landed == want and landed != MANUAL_MODE
        if not ok:
            log.error(
                "group %s: RELEASE NOT CONFIRMED, pwm%s_enable reads %r (wanted %r)",
                self.name,
                self.header,
                landed,
                want,
            )
        return ok


# ---------------------------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------------------------


class Controller:
    """The control loop: read sensors, compute demand, damp, apply."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.interval: float = float(cfg.get("interval", 3.0))
        self.rise: float = float(cfg.get("rise_rate", 1.0))
        self.fall: float = float(cfg.get("fall_rate", 0.08))
        self.deadband: int = int(cfg.get("deadband_pwm", 3))
        self.fail_tolerance: int = int(cfg.get("sensor_fail_tolerance", 5))
        self.failsafe_floor_pwm: int = int(cfg.get("failsafe_floor_pwm", 140))
        self.metrics_path: str | None = cfg.get("metrics_path")
        self.pump_headers: set[int] = {int(h) for h in cfg.get("pump_headers", [])}
        # {name: {path, scale?, unit?}} — ancillary readings for context, not control.
        self.extras: dict[str, dict] = cfg.get("extra_metrics", {}) or {}

        self.sensors: dict[str, Sensor] = {}
        for s in cfg.get("sensors", []):
            sensor = Sensor(
                name=s["name"],
                chip=s["chip"],
                floor=float(s["floor"]),
                ceiling=float(s["ceiling"]),
                gamma=float(s.get("gamma", 1.0)),
                label=s.get("label"),
                index=s.get("index"),
                path_contains=s.get("path_contains"),
            )
            self.sensors[sensor.name] = sensor

        self.groups: list[Group] = []
        for g in cfg.get("groups", []):
            group = Group(
                name=g["name"],
                header=int(g["header"]),
                chip=g["chip"],
                sensors=list(g["sensors"]),
                pwm_min=int(g["pwm_min"]),
                pwm_max=int(g.get("pwm_max", 255)),
                note=g.get("note", ""),
            )
            self.groups.append(group)

        self._validate()

    def _validate(self) -> None:
        """Reject a configuration that cannot do what it claims, before touching hardware."""
        if not self.sensors:
            raise ConfigError("no sensors declared -- nothing could drive the fans")
        if not self.groups:
            raise ConfigError("no fan groups declared -- there would be nothing to control")

        for g in self.groups:
            # A pump is not a fan: driving one down risks cavitation and loss of coolant flow,
            # and its RPM says nothing about whether coolant is moving.
            if g.header in self.pump_headers:
                raise ConfigError(
                    f"group {g.name!r} targets header {g.header}, declared as a PUMP header. "
                    f"Driving a pump from a fan curve risks cavitation and loss of coolant flow."
                )
            if not g.sensors:
                raise ConfigError(f"group {g.name!r} lists no sensors -- its demand would be 0")
            unknown = [s for s in g.sensors if s not in self.sensors]
            if unknown:
                raise ConfigError(
                    f"group {g.name!r} references undeclared sensor(s): {', '.join(unknown)}"
                )
            if not 0 <= g.pwm_min <= g.pwm_max <= 255:
                raise ConfigError(
                    f"group {g.name!r}: need 0 <= pwm_min ({g.pwm_min}) <= "
                    f"pwm_max ({g.pwm_max}) <= 255"
                )

    def resolve(self) -> None:
        """Resolve every sensor and group, or refuse to start.

        A declared sensor that does not resolve must NOT be quietly dropped: it would fall out
        of the max and lower fan speed exactly when something is unmonitored.
        """
        for sensor in self.sensors.values():
            sensor.resolve()
            log.info(
                "sensor %s -> %s (%.0f-%.0fC, gamma %.2f%s)",
                sensor.name,
                sensor.path,
                sensor.floor,
                sensor.ceiling,
                sensor.gamma,
                f", hw limit {sensor.hw_crit:.0f}C" if sensor.hw_crit else "",
            )
        for group in self.groups:
            group.resolve()
            log.info(
                "group %s -> header %s on %s, pwm %d-%d, sensors: %s",
                group.name,
                group.header,
                group.chip,
                group.pwm_min,
                group.pwm_max,
                ", ".join(group.sensors),
            )

    def step(self) -> None:
        """One iteration: read, compute, damp, apply."""
        readings: dict[str, float | None] = {}
        demands: dict[str, float] = {}
        for name, sensor in self.sensors.items():
            temp = sensor.read()
            readings[name] = temp
            if temp is not None:
                demands[name] = sensor.demand(temp)

        for group in self.groups:
            usable = [s for s in group.sensors if s in demands]
            lost = [
                s
                for s in group.sensors
                if s not in demands and self.sensors[s].fail_count >= self.fail_tolerance
            ]

            if lost:
                self._enter_failsafe(group, lost)
                continue
            if group.in_failsafe:
                self._exit_failsafe(group)
            if not usable:
                # Transient: hold what we have rather than reacting to a single bad poll.
                continue

            driver = max(usable, key=lambda s: demands[s])
            target = demands[driver]
            group.driver = driver

            # Asymmetric damping: rise fast (thermal safety), fall slowly (a brief spike must
            # not leave the fans hunting -- variation is what the ear catches).
            rate = self.rise if target > group.smoothed else self.fall
            group.smoothed += (target - group.smoothed) * rate

            span = group.pwm_max - group.pwm_min
            duty = int(round(group.pwm_min + span * group.smoothed / 100.0))
            duty = max(group.pwm_min, min(group.pwm_max, duty))

            # Deadband: do not rewrite the register for a change nobody could hear.
            #
            # BUT ONLY WHEN WE ARE STILL IN CONTROL. `applied` is read back from the pwm duty
            # register, which holds a value in automatic mode too -- the hardware curve writes
            # it. So if something released the header (a stop, a crash's ExecStopPost, a hand
            # run of the restore play), the chip's own duty can sit within the deadband of the
            # last duty we applied, the comparison says "no change needed", and the header is
            # NEVER taken back: the daemon then runs forever believing it is in control while
            # the hardware curve actually drives the fans.
            #
            # The symptom: the service is active, its loop running and metrics fresh, while the
            # headers sit in automatic mode.
            # The MODE is the authority on who is in control, never the duty.
            in_control = group._read(f"pwm{group.header}_enable") == MANUAL_MODE
            if (
                in_control
                and group.applied is not None
                and abs(duty - group.applied) < self.deadband
            ):
                continue
            if not group.apply(duty):
                log.error("group %s: failed to apply duty %d", group.name, duty)

        self._write_metrics(readings, demands)

    def _enter_failsafe(self, group: Group, lost: list[str]) -> None:
        """Hand a group back to the hardware curve, with its floor raised.

        WHY THE HARDWARE CURVE RATHER THAN A FIXED DUTY: the chip's curve is real thermal
        regulation that tracks CPU temperature, where a fixed duty is a guess that is either
        wasteful or insufficient.

        WHY THE FLOOR IS RAISED ANYWAY: the chip's curve can only follow CPU temperature. If the
        sensor we lost is the GPU -- mid-game, GPU at 90C, CPU comparatively cool -- the chip
        would see a coolish CPU and run the fans slow while the GPU cooks. Raising the curve's
        low points means it cannot go quiet while blind.
        """
        if group.in_failsafe:
            return
        group.in_failsafe = True
        log.error(
            "group %s: FAIL-SAFE, sensor(s) unreadable: %s. Releasing to the hardware curve "
            "with a raised floor.",
            group.name,
            ", ".join(lost),
        )
        group.release()
        self._set_curve_floor(group, self.failsafe_floor_pwm)

    def _exit_failsafe(self, group: Group) -> None:
        group.in_failsafe = False
        group.applied = None
        log.warning("group %s: sensors recovered, resuming normal control", group.name)

    def _set_curve_floor(self, group: Group, floor_pwm: int) -> None:
        """Raise the low points of the chip's own curve, so a blind fallback cannot be quiet."""
        assert group.hwmon is not None
        for point in (1, 2, 3):
            leaf = f"pwm{group.header}_auto_point{point}_pwm"
            current = group._read(leaf)
            if current is None or not current.isdigit():
                continue
            if int(current) < floor_pwm:
                group._write(leaf, str(floor_pwm))

    def _write_metrics(self, readings: dict[str, float | None], demands: dict[str, float]) -> None:
        """Emit Prometheus textfile metrics, written atomically.

        Textfile rather than an HTTP endpoint because it needs no listener
        and costs nothing on a host with no scraper: the file simply sits there until a node exporter's
        textfile collector is deployed, at which point it is collected with no change here.

        Written to a temp file and renamed, so a scrape never sees a half-written file.
        """
        if not self.metrics_path:
            return
        lines = [
            "# HELP fand_sensor_temp_celsius Temperature of a declared sensor.",
            "# TYPE fand_sensor_temp_celsius gauge",
        ]
        for name, temp in readings.items():
            if temp is not None:
                lines.append(f'fand_sensor_temp_celsius{{sensor="{name}"}} {temp:.2f}')
        lines += [
            "# HELP fand_sensor_demand_ratio Normalised cooling demand, 0-100.",
            "# TYPE fand_sensor_demand_ratio gauge",
        ]
        for name, value in demands.items():
            lines.append(f'fand_sensor_demand_ratio{{sensor="{name}"}} {value:.2f}')
        lines += [
            "# HELP fand_sensor_readable Whether a declared sensor could be read.",
            "# TYPE fand_sensor_readable gauge",
        ]
        for name, temp in readings.items():
            lines.append(f'fand_sensor_readable{{sensor="{name}"}} {0 if temp is None else 1}')
        lines += [
            "# HELP fand_group_pwm Duty cycle actually applied, 0-255.",
            "# TYPE fand_group_pwm gauge",
            "# HELP fand_group_rpm Measured fan speed.",
            "# TYPE fand_group_rpm gauge",
            "# HELP fand_group_failsafe Whether a group is in fail-safe.",
            "# TYPE fand_group_failsafe gauge",
            "# HELP fand_group_driving_demand Demand of the sensor currently driving a group.",
            "# TYPE fand_group_driving_demand gauge",
        ]
        # ---- the CURVE ITSELF, not just the current point on it ----------------------------
        #
        # Emitted so a dashboard can plot EXPECTED against ACTUAL. Without these a graph shows
        # only where the fans are, never where the configuration says they should be, so a
        # daemon that is silently mis-applying duty looks identical to one working perfectly.
        # They are constants per config, which is the point: they become the reference line.
        lines += [
            "# HELP fand_sensor_floor_celsius Temperature below which this sensor demands nothing.",
            "# TYPE fand_sensor_floor_celsius gauge",
            "# HELP fand_sensor_ceiling_celsius Temperature at which this sensor demands 100%.",
            "# TYPE fand_sensor_ceiling_celsius gauge",
            "# HELP fand_sensor_gamma Curve shape: >1 flat then steep, <1 ramps early.",
            "# TYPE fand_sensor_gamma gauge",
            "# HELP fand_sensor_hw_limit_celsius The limit the hardware itself declares, if any.",
            "# TYPE fand_sensor_hw_limit_celsius gauge",
        ]
        for name, sensor in self.sensors.items():
            lines.append(f'fand_sensor_floor_celsius{{sensor="{name}"}} {sensor.floor:.1f}')
            lines.append(f'fand_sensor_ceiling_celsius{{sensor="{name}"}} {sensor.ceiling:.1f}')
            lines.append(f'fand_sensor_gamma{{sensor="{name}"}} {sensor.gamma:.3f}')
            if sensor.hw_crit is not None:
                lines.append(
                    f'fand_sensor_hw_limit_celsius{{sensor="{name}"}} {sensor.hw_crit:.1f}'
                )

        lines += [
            "# HELP fand_group_pwm_min Configured minimum duty for this group.",
            "# TYPE fand_group_pwm_min gauge",
            "# HELP fand_group_pwm_max Configured maximum duty for this group.",
            "# TYPE fand_group_pwm_max gauge",
            "# HELP fand_group_expected_pwm Duty the curve implies for the current demand.",
            "# TYPE fand_group_expected_pwm gauge",
            "# HELP fand_group_demand_ratio Damped demand actually driving this group, 0-100.",
            "# TYPE fand_group_demand_ratio gauge",
            "# HELP fand_group_curve_pwm Duty this group would run at a given demand.",
            "# TYPE fand_group_curve_pwm gauge",
        ]

        for group in self.groups:
            tag = f'group="{group.name}",header="{group.header}"'
            if group.applied is not None:
                lines.append(f"fand_group_pwm{{{tag}}} {group.applied}")
            rpm = group.rpm()
            if rpm is not None:
                lines.append(f"fand_group_rpm{{{tag}}} {rpm}")
            lines.append(f"fand_group_failsafe{{{tag}}} {1 if group.in_failsafe else 0}")
            lines.append(f"fand_group_pwm_min{{{tag}}} {group.pwm_min}")
            lines.append(f"fand_group_pwm_max{{{tag}}} {group.pwm_max}")
            lines.append(f"fand_group_demand_ratio{{{tag}}} {group.smoothed:.2f}")

            # EXPECTED duty for the demand right now. Plotted against fand_group_pwm this shows
            # whether the daemon is applying what its own configuration implies -- the deadband
            # and the damping both make them differ legitimately, and a persistent gap does not.
            span = group.pwm_max - group.pwm_min
            expected = int(round(group.pwm_min + span * group.smoothed / 100.0))
            lines.append(f"fand_group_expected_pwm{{{tag}}} {expected}")

            # The whole curve as a series of points, so a dashboard can draw the configured
            # response as a reference line rather than reconstructing it from three scalars.
            for pct in range(0, 101, 10):
                curve_pwm = int(round(group.pwm_min + span * pct / 100.0))
                lines.append(f'fand_group_curve_pwm{{{tag},demand="{pct}"}} {curve_pwm}')

            if group.driver:
                # The DRIVING sensor is named deliberately: "GPU mem at 82% demand" is
                # actionable, a bare "fans at 60%" is not.
                lines.append(
                    f'fand_group_driving_demand{{{tag},sensor="{group.driver}"}} '
                    f"{demands.get(group.driver, 0.0):.2f}"
                )

        lines += self._extra_metrics()

        try:
            target = pathlib.Path(self.metrics_path)
            tmp = target.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n")
            os.replace(tmp, target)
        except OSError as exc:
            log.warning("could not write metrics to %s: %s", self.metrics_path, exc)

    def _extra_metrics(self) -> list[str]:
        """Context metrics beyond the control loop's own inputs.

        WHY COLLECT THINGS THE DAEMON DOES NOT ACT ON. A fan graph alone cannot answer "why did
        it ramp?" — GPU power and utilisation, VRAM, clocks and the GPU's own fan are what turn
        a speed change into an explanation. They cost one file read each and are the difference
        between a dashboard that shows what happened and one that shows why.

        Declared as paths in config rather than hardcoded, so a different machine collects a
        different set without touching this file.
        """
        out: list[str] = []
        if not self.extras:
            return out
        out += [
            "# HELP fand_extra Ancillary hardware readings collected for context.",
            "# TYPE fand_extra gauge",
        ]
        for name, spec in self.extras.items():
            try:
                raw = pathlib.Path(spec["path"]).read_text().strip()
            except OSError:
                continue
            # Some files hold a whole table (pp_dpm_sclk); take the ACTIVE line, marked with '*'.
            if "\n" in raw or "*" in raw:
                active = [ln for ln in raw.splitlines() if "*" in ln]
                if not active:
                    continue
                digits = "".join(c for c in active[0].split(":")[-1] if c.isdigit())
                raw = digits or "0"
            try:
                value = float(raw) / float(spec.get("scale", 1))
            except ValueError:
                continue
            unit = spec.get("unit", "")
            label = f'metric="{name}"' + (f',unit="{unit}"' if unit else "")
            out.append(f"fand_extra{{{label}}} {value:.3f}")
        return out

    def release_all(self) -> bool:
        ok = True
        for group in self.groups:
            ok &= group.release()
        return ok


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def _setup_logging(to_journal: bool) -> None:
    log.setLevel(logging.INFO)
    if to_journal:
        # systemd captures stderr into the journal, so plain stderr IS journald here -- no
        # extra dependency, and the format stays readable under `journalctl -u`.
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fan control by normalised component demand.")
    parser.add_argument("--config", required=True, help="JSON config, rendered from inventory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="resolve and validate everything, report, and exit WITHOUT touching any fan",
    )
    parser.add_argument("--once", action="store_true", help="run a single control step and exit")
    parser.add_argument(
        "--release-only",
        action="store_true",
        help=(
            "release every declared header to the hardware curve and exit. Used by the unit's "
            "ExecStop, so a stop is an explicit, verified handback rather than a bare SIGTERM."
        ),
    )
    parser.add_argument("--foreground", action="store_true", help="log to stdout, not journald")
    args = parser.parse_args()

    _setup_logging(to_journal=not args.foreground)

    try:
        cfg = json.loads(pathlib.Path(args.config).read_text())
    except (OSError, ValueError) as exc:
        log.error("cannot read config %s: %s", args.config, exc)
        return 2

    try:
        controller = Controller(cfg)
        controller.resolve()
    except ConfigError as exc:
        # Refusing to start is the correct response to a bad config. Starting with fewer sensors
        # than declared would lower fan speed exactly when something is unmonitored.
        log.error("configuration refused: %s", exc)
        return 2

    if args.release_only:
        ok = controller.release_all()
        log.info("release-only: %s", "all headers on the hardware curve" if ok else "FAILED")
        return 0 if ok else 1

    if args.check:
        log.info(
            "check passed: %d sensor(s), %d group(s), nothing was written",
            len(controller.sensors),
            len(controller.groups),
        )
        return 0

    stopping = {"now": False}

    def _stop(signum: int, _frame: Any) -> None:
        log.info("signal %d -- releasing headers to the hardware curve", signum)
        stopping["now"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Tell systemd we are up only AFTER every sensor resolved, so a failed resolution is a
    # failed start rather than a service that reports ready and controls nothing.
    _notify("READY=1")
    log.info(
        "fand started: %d sensor(s), %d group(s), interval %.1fs",
        len(controller.sensors),
        len(controller.groups),
        controller.interval,
    )

    exit_code = 0
    try:
        while not stopping["now"]:
            try:
                controller.step()
            except Exception:  # noqa: BLE001 -- a control loop must not die on one bad step
                log.exception("control step failed; holding current duties")
            _notify("WATCHDOG=1")
            if args.once:
                break
            time.sleep(controller.interval)
    finally:
        # Every exit path releases. Losing this daemon must return the fans to HARDWARE control,
        # never leave them pinned at whatever was last written.
        if not controller.release_all():
            log.error(
                "one or more headers were NOT confirmed back under automatic control -- "
                "run the fan restore play"
            )
            exit_code = 1
        else:
            log.info("all headers released to the hardware curve")
    return exit_code


def _notify(state: str) -> None:
    """Minimal sd_notify. Avoids a python3-systemd dependency on an image-based OS."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        import socket

        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(state.encode())
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
