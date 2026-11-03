# SPDX-License-Identifier: GPL-3.0-or-later
"""Argument spec for config_fan_control. Generated files come from here — see tools/argspec."""

from __future__ import annotations

DEFAULT_AUTHOR = "Collection maintainers"
from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Fan control by normalised per-component thermal demand",
            description=[
                "Deploys a daemon that normalises each sensor to a 0-100 demand against its",
                "OWN floor/ceiling/gamma, and drives each fan group from the MAXIMUM demand",
                "across the sensors it cares about.",
                "Exists because the Super-I/O chip can only steer off its own temp channels —",
                "amdgpu, nvme and k10temp are invisible to it, so GPU-aware case fans are",
                "outside what the hardware can express.",
                "Every machine-specific fact (which sensors, which headers, which are pumps)",
                "is site config: a second machine needs an inventory block, not a code change.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "fand_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Gate. Without it the role validates the config against the live",
                        "hardware and reports, writing nothing and starting nothing.",
                    ],
                ),
                "fand_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Whether the service should be running. Setting false stops and",
                        "disables it, which releases every header to the hardware curve —",
                        "the safe direction.",
                    ],
                ),
                "fand_sensors": OptionSpec(
                    type="list",
                    elements="dict",
                    required=True,
                    description=[
                        "Temperature inputs. Each: `name`, `chip` (hwmon chip name), one of",
                        "`label` or `index`, `floor`, `ceiling`, `gamma`, and optionally",
                        "`path_contains` to disambiguate two chips of the same name (a board",
                        "with an iGPU and a discrete card has two `amdgpu`).",
                        "REQUIRED with no default: a role cannot know what sensors a machine",
                        "has, and guessing would silently monitor the wrong things.",
                    ],
                ),
                "fand_groups": OptionSpec(
                    type="list",
                    elements="dict",
                    required=True,
                    description=[
                        "Fan groups. Each: `name`, `header` (pwm index), `chip`, `sensors`",
                        "(which inputs this group follows), `pwm_min`, `pwm_max`, `note`.",
                        "`pwm_min` must clear the fans' measured stall duty.",
                        "REQUIRED with no default, for the same reason as the sensors.",
                    ],
                ),
                "fand_extra_metrics": OptionSpec(
                    type="dict",
                    required=False,
                    default={},
                    description=[
                        "Ancillary sysfs readings collected for CONTEXT, not control:",
                        "{name: {path, scale, unit}}. A fan graph alone cannot answer 'why did",
                        "it ramp?' — GPU power, utilisation, VRAM, clocks and the card's own",
                        "fan are what turn a speed change into an explanation.",
                        "Paths rather than hardcoded readings, so another machine collects a",
                        "different set without touching the daemon.",
                    ],
                ),
                "fand_pump_headers": OptionSpec(
                    type="list",
                    elements="int",
                    required=False,
                    default=[],
                    description=[
                        "Headers driving a pump. The daemon REFUSES to control these: driving",
                        "a pump from a fan curve risks cavitation and loss of coolant flow,",
                        "and a pump's RPM says nothing about whether coolant is moving.",
                    ],
                ),
                "fand_chip": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "The Super-I/O chip carrying the fan headers (e.g. nct6799). Used by",
                        "the unit's ExecStopPost fallback, which must name it literally.",
                    ],
                ),
                "fand_interval": OptionSpec(
                    type="float",
                    required=False,
                    default=3.0,
                    description="Seconds between control steps.",
                ),
                "fand_rise_rate": OptionSpec(
                    type="float",
                    required=False,
                    default=1.0,
                    description=[
                        "How fast duty rises toward a higher demand, 0-1. Default 1.0 (immediate)",
                        "because thermal safety takes priority on the way up.",
                    ],
                ),
                "fand_fall_rate": OptionSpec(
                    type="float",
                    required=False,
                    default=0.08,
                    description=[
                        "How fast duty falls toward a lower demand, 0-1. Deliberately slow: fans",
                        "that chase transients are worse than steady noise, because variation is",
                        "what the ear catches.",
                    ],
                ),
                "fand_deadband_pwm": OptionSpec(
                    type="int",
                    required=False,
                    default=3,
                    description="Duty change below this is not written at all.",
                ),
                "fand_sensor_fail_tolerance": OptionSpec(
                    type="int",
                    required=False,
                    default=5,
                    description=[
                        "Consecutive read failures before a sensor counts as lost. Below this",
                        "the last good demand is held — one bad poll is not a reason to act.",
                    ],
                ),
                "fand_failsafe_floor_pwm": OptionSpec(
                    type="int",
                    required=False,
                    default=140,
                    description=[
                        "On sensor loss the group is released to the hardware curve AND the",
                        "curve's low points raised to at least this. The chip's curve only",
                        "follows CPU temperature, so a lost GPU sensor would otherwise let it",
                        "run quiet while the GPU cooks.",
                    ],
                ),
                "fand_watchdog_sec": OptionSpec(
                    type="int",
                    required=False,
                    default=30,
                    description=[
                        "systemd watchdog. Catches a hung-but-alive daemon, which neither",
                        "ExecStop nor ExecStopPost would ever fire for.",
                    ],
                ),
                "fand_path": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/local/bin/fand",
                    description="Where the daemon is installed.",
                ),
                "fand_config_path": OptionSpec(
                    type="str",
                    required=False,
                    default="/etc/fand.json",
                    description="Where the rendered config is written.",
                ),
                "fand_metrics_path": OptionSpec(
                    type="str",
                    required=False,
                    default="/var/lib/node_exporter/textfile_collector/fand.prom",
                    description=[
                        "Prometheus textfile output. Costs nothing on a host with no scraper —",
                        "the file simply waits until Alloy's unix exporter is deployed.",
                    ],
                ),
                "fand_loadtest": OptionSpec(
                    type="dict",
                    required=False,
                    default={},
                    description=[
                        "One load test: `load_command` (argv), `sensors` (which to watch),",
                        "`abort_above` (a list of {sensor, celsius} — REQUIRED, a load test",
                        "with no abort temperature is just a way to overheat a machine on a",
                        "timer), and optional `cooldown_samples` and `container`.",
                        "`container` names an image to run the load in, rather than layering a",
                        "tool onto an image-based OS where it would slow every update and",
                        "re-resolve on each rebase.",
                        "Declared per test in its own play, because what stresses a GPU and",
                        "what stresses an NVMe have nothing in common.",
                    ],
                ),
                "fand_loadtest_name": OptionSpec(
                    type="str",
                    required=False,
                    default="run",
                    description=[
                        "Short name for this test, used in the result filenames so two tests do",
                        "not overwrite each other's timeline.",
                    ],
                ),
                "fand_loadtest_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description="Gate. Without it the test reports and verifies wiring only.",
                ),
                "fand_loadtest_duration": OptionSpec(
                    type="int",
                    required=False,
                    default=180,
                    description="Maximum seconds of load. An abort can end it sooner.",
                ),
                "fand_loadtest_interval": OptionSpec(
                    type="float",
                    required=False,
                    default=2.0,
                    description="Seconds between samples. Also the abort-check period.",
                ),
                "fand_loadtest_path": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/local/bin/fand-loadtest",
                    description="Where the harness is installed on the target.",
                ),
                "fand_loadtest_config": OptionSpec(
                    type="str",
                    required=False,
                    default="/etc/fand-loadtest.json",
                    description="Where the rendered test config is written.",
                ),
                "fand_loadtest_results": OptionSpec(
                    type="str",
                    required=False,
                    default="/var/tmp/fand-loadtest-{{ fand_loadtest_name | default('run') }}.json",
                    description="Where the timeline is written on the target.",
                ),
                "fand_loadtest_fetch_to": OptionSpec(
                    # No default: where a result lands on the controller is the caller's layout.
                    type="str",
                    required=False,
                    description=[
                        "ABSOLUTE path on the CONTROLLER the load-test timeline is fetched to.",
                        "Required by the loadtest entrypoint. Name it per test: a shared",
                        "filename means the second run silently overwrites the first.",
                        "Use an absolute path: delegate_to localhost resolves a relative dest",
                        "against the playbook directory, not the working directory.",
                    ],
                ),
                "fand_discover_path": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/local/bin/fand-discover",
                    description="Where the discovery helper is installed on the target.",
                ),
                "fand_discover_output": OptionSpec(
                    # No default: where a draft lands on the controller is the caller's layout.
                    type="str",
                    required=False,
                    description=[
                        "ABSOLUTE path ON THE CONTROLLER the proposed inventory draft is written",
                        "to. Required by the discover entrypoint when fand_discover_save is true.",
                        "Local rather than on the target: it is a draft destined for",
                        "inventory, and leaving it on the machine invites treating it as live",
                        "config. Keep it outside any directory a linter walks: a stray draft",
                        "there is parsed as a playbook and fails the lint run.",
                    ],
                ),
                "fand_discover_save": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description="Write the draft to fand_discover_output as well as printing it.",
                ),
                "fand_discover_modules": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=["nct6775", "it87", "coretemp", "k10temp", "drivetemp", "spd5118"],
                    description=[
                        "Sensor modules to try loading before surveying. Without a Super-I/O",
                        "module the fan headers do not exist in sysfs, and the survey would",
                        "report no controllable headers when the module simply was not loaded.",
                    ],
                ),
                "fand_python": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/bin/python3",
                    description="Interpreter for the daemon. Stdlib only; no packages needed.",
                ),
                "fand_unit": OptionSpec(
                    type="str",
                    required=False,
                    default="fand.service",
                    description="systemd unit name.",
                ),
            },
        )
    },
)
