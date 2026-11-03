#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for fand.py. Run: python3 files/test_fand.py

EVERY TEST PROVES A FAILURE IS POSSIBLE, not just that the happy path passes. A guard that reads
as a real check but can never fire is worse than none, so a refusal here is only
credible if something demonstrates it firing. Each `must_refuse` case is a configuration that
MUST be rejected; if the refusal ever stops working, the test fails rather than quietly passing.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def load():
    spec = importlib.util.spec_from_file_location("fand", HERE / "fand.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registering in sys.modules is REQUIRED: @dataclass resolves annotations via
    # sys.modules[cls.__module__], which is None for an unregistered importlib module.
    sys.modules["fand"] = module
    spec.loader.exec_module(module)
    return module


m = load()

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")


BASE = {
    "interval": 1,
    "metrics_path": None,
    "pump_headers": [7],
    "sensors": [
        {
            "name": "gpu",
            "chip": "amdgpu",
            "label": "junction",
            "floor": 45,
            "ceiling": 100,
            "gamma": 1.6,
        },
        {
            "name": "cpu",
            "chip": "k10temp",
            "label": "Tctl",
            "floor": 50,
            "ceiling": 88,
            "gamma": 1.4,
        },
    ],
    "groups": [
        {"name": "case", "header": 2, "chip": "nct6799", "sensors": ["gpu", "cpu"], "pwm_min": 51}
    ],
}


def sensor(**kw):
    spec = dict(name="s", chip="c", floor=40.0, ceiling=80.0, gamma=1.0)
    spec.update(kw)
    return m.Sensor(**spec)


def must_refuse(mutate, why: str) -> None:
    bad = json.loads(json.dumps(BASE))
    mutate(bad)
    try:
        m.Controller(bad)
    except m.ConfigError:
        check(f"refuses: {why}", True)
        return
    check(f"refuses: {why}", False, "accepted a config it should have rejected")


print("demand normalisation")
s = sensor(floor=45, ceiling=100, gamma=1.6)
check("below floor is 0", s.demand(30) == 0.0)
check("at ceiling is 100", s.demand(100) == 100.0)
check("above ceiling clamps", s.demand(150) == 100.0)
check(
    "gamma>1 is concave (quiet low, hard top)",
    0 < s.demand(72.5) < 50,
    f"midpoint={s.demand(72.5):.1f}%",
)
check("gamma<1 ramps early", sensor(floor=40, ceiling=80, gamma=0.8).demand(60) > 50)
check("degenerate floor==ceiling is full demand", sensor(floor=50, ceiling=50).demand(10) == 100.0)

print("worst component wins")
c = m.Controller(BASE)
dg, dc = c.sensors["gpu"].demand(72), c.sensors["cpu"].demand(65)
check("hotter-relative-to-its-own-limits sensor wins", dg > dc, f"gpu={dg:.0f}% cpu={dc:.0f}%")
cool_gpu, hot_cpu = c.sensors["gpu"].demand(50), c.sensors["cpu"].demand(85)
check(
    "and the winner changes when the other is stressed",
    hot_cpu > cool_gpu,
    f"gpu={cool_gpu:.0f}% cpu={hot_cpu:.0f}%",
)

print("configuration refusals")
must_refuse(lambda c: c["groups"][0].update(header=7), "a group targeting a PUMP header")
must_refuse(lambda c: c["groups"][0].update(sensors=[]), "a group with no sensors")
must_refuse(lambda c: c["groups"][0].update(sensors=["nope"]), "an undeclared sensor")
must_refuse(lambda c: c.update(sensors=[]), "no sensors at all")
must_refuse(lambda c: c.update(groups=[]), "no groups at all")
must_refuse(lambda c: c["groups"][0].update(pwm_min=200, pwm_max=100), "pwm_min above pwm_max")
must_refuse(lambda c: c["groups"][0].update(pwm_max=300), "pwm_max above 255")

print("sensor resolution refuses rather than guessing")
missing = sensor(name="ghost", chip="definitely-not-a-real-chip", label="x")
try:
    missing.resolve()
    check("a missing chip refuses", False, "resolved a chip that does not exist")
except m.ConfigError:
    check("a missing chip refuses", True)

# Each fixture gets its OWN root, because HWMON_ROOT is globbed: reusing a shared temp parent
# let a previous run's leftover chip dir be found too, and the duplicate-chip check correctly
# refused. That was test pollution, not a daemon bug — but it is exactly the kind of thing that
# gets "fixed" by weakening the check, so the fixture is isolated instead.
fixture_root = pathlib.Path(tempfile.mkdtemp())
fake = fixture_root / "hwmon9"
fake.mkdir()
(fake / "name").write_text("faux\n")
(fake / "temp1_label").write_text("junction\n")
(fake / "temp1_input").write_text("45000\n")
(fake / "temp1_crit").write_text("110000\n")
orig_root = m.HWMON_ROOT
try:
    m.HWMON_ROOT = fixture_root
    ok_sensor = sensor(name="g", chip="faux", label="junction", floor=45, ceiling=100)
    ok_sensor.resolve()
    check("resolves a real chip by name+label", ok_sensor.path is not None)
    check(
        "reads the hardware's declared limit",
        ok_sensor.hw_crit == 110.0,
        f"hw_crit={ok_sensor.hw_crit}",
    )
    check("reads a temperature", ok_sensor.read() == 45.0)

    over = sensor(name="g", chip="faux", label="junction", floor=45, ceiling=120)
    try:
        over.resolve()
        check(
            "refuses a ceiling above the hardware's own crit",
            False,
            "accepted 120C over a 110C crit",
        )
    except m.ConfigError:
        check("refuses a ceiling above the hardware's own crit", True)

    wrong_label = sensor(name="g", chip="faux", label="nonexistent")
    try:
        wrong_label.resolve()
        check("refuses an unknown label", False)
    except m.ConfigError:
        check("refuses an unknown label", True)

    # Two chips of the same name with no predicate must REFUSE, not pick one: a board with an
    # iGPU and a discrete card carries two `amdgpu` chips.
    twin = fixture_root / "hwmon8"
    twin.mkdir()
    (twin / "name").write_text("faux\n")
    (twin / "temp1_label").write_text("junction\n")
    (twin / "temp1_input").write_text("30000\n")
    ambiguous = sensor(name="g", chip="faux", label="junction", floor=45, ceiling=100)
    try:
        ambiguous.resolve()
        check("refuses two same-named chips with no predicate", False, "picked one arbitrarily")
    except m.ConfigError:
        check("refuses two same-named chips with no predicate", True)

    disambiguated = sensor(
        name="g", chip="faux", label="junction", floor=45, ceiling=100, path_contains="hwmon9"
    )
    disambiguated.resolve()
    check("path_contains disambiguates", disambiguated.read() == 45.0)
finally:
    m.HWMON_ROOT = orig_root

print("damping is asymmetric")
ctl = m.Controller(BASE)
g = ctl.groups[0]
g.smoothed = 0.0
for _ in range(3):
    g.smoothed += (100 - g.smoothed) * ctl.rise
up = g.smoothed
g.smoothed = 100.0
for _ in range(3):
    g.smoothed += (0 - g.smoothed) * ctl.fall
down = g.smoothed
check("rises fast (thermal safety)", up > 90, f"0 -> {up:.0f}% in 3 steps")
check("falls slowly (no hunting)", down > 60, f"100 -> {down:.0f}% in 3 steps")
check("rise is faster than fall", (100 - up) < down)

print("release never lands on manual mode")
grp = m.Group(name="g", header=2, chip="x", sensors=["s"], pwm_min=51)
fakehw = pathlib.Path(tempfile.mkdtemp())
(fakehw / "pwm2_enable").write_text("1\n")
grp.hwmon = fakehw
grp.orig_enable = "1"  # the stranded-header case: restoring MANUAL would verify the broken state
check(
    "a captured MANUAL mode is redirected to automatic",
    grp.release() and (fakehw / "pwm2_enable").read_text().strip() == "5",
)

print("deadband never masks a lost header")
# The regression: `applied` comes from the duty register, which holds a value in AUTOMATIC mode
# too, so a released header can sit within the deadband of the last applied duty. If the
# deadband is consulted without checking the MODE, the header is never retaken and the daemon
# runs forever believing it is in control.
dbhw = pathlib.Path(tempfile.mkdtemp())
(dbhw / "pwm2_enable").write_text("5\n")  # released: hardware is in control
(dbhw / "pwm2").write_text("54\n")  # ...at a duty within the deadband of ours
(dbhw / "fan2_input").write_text("600\n")
dbg = m.Group(name="g", header=2, chip="x", sensors=["s"], pwm_min=51, pwm_max=191)
dbg.hwmon = dbhw
dbg.applied = 54
check("a released header is detected as not-in-control", dbg._read("pwm2_enable") != m.MANUAL_MODE)
check(
    "applying it takes the header back to manual",
    dbg.apply(54) and (dbhw / "pwm2_enable").read_text().strip() == m.MANUAL_MODE,
)

print("metrics describe the CURVE, not just the current point")
# Without these a dashboard can only plot where the fans ARE, never where the configuration
# says they SHOULD be — so a daemon silently mis-applying duty looks identical to a healthy one.
mhw = pathlib.Path(tempfile.mkdtemp())
(mhw / "pwm2_enable").write_text("1\n")
(mhw / "pwm2").write_text("100\n")
(mhw / "fan2_input").write_text("900\n")
mctl = m.Controller(BASE)
mg = mctl.groups[0]
mg.hwmon = mhw
mg.applied = 100
mg.smoothed = 50.0
mg.driver = "gpu"
out = pathlib.Path(tempfile.mkdtemp()) / "fand.prom"
mctl.metrics_path = str(out)
for sname, sspec in mctl.sensors.items():
    sspec.path = mhw / "fan2_input"  # any readable file; only the config fields are emitted
mctl._write_metrics({"gpu": 72.0, "cpu": 65.0}, {"gpu": 32.0, "cpu": 27.0})
text = out.read_text()
check("emits each sensor's floor", 'fand_sensor_floor_celsius{sensor="gpu"} 45.0' in text)
check("emits each sensor's ceiling", 'fand_sensor_ceiling_celsius{sensor="gpu"} 100.0' in text)
check("emits each sensor's gamma", 'fand_sensor_gamma{sensor="gpu"} 1.600' in text)
check(
    "emits the group's configured duty range",
    'fand_group_pwm_min{group="case",header="2"} 51' in text,
)
check("emits the EXPECTED duty for the current demand", "fand_group_expected_pwm" in text)
# Count DATA lines only: a bare `count` includes the metric's own # HELP and # TYPE lines and
# reports 13 for 11 points.
_curve_points = [ln for ln in text.splitlines() if ln.startswith("fand_group_curve_pwm")]
check(
    "emits the whole curve as reference points (0-100 in tens)",
    len(_curve_points) == 11,
    f"{len(_curve_points)} points",
)
check("names the driving sensor", 'sensor="gpu"} 32.00' in text)
# The expected duty must follow the configuration, not a hardcoded guess: at 50% demand with
# pwm_min 51 and pwm_max 255 it is the midpoint.
check(
    "expected duty is derived from min/max and demand",
    f'fand_group_expected_pwm{{group="case",header="2"}} {round(51 + (255 - 51) * 0.5)}' in text,
)

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
