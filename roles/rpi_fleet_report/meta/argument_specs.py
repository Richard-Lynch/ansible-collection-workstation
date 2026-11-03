# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Whole-fleet drift report for the Pi nodes",
            description=[
                "READ-ONLY. Answers 'is the fleet in the state the repo says?' across every Pi:",
                "boot device, EEPROM order, rescue-card sealing, watchdog, throttling, and",
                "whether each node is still actually stateless.",
                "",
                "Exists so drift is found ON PURPOSE, on a schedule, rather than during an",
                "incident: state that nothing reports keeps drifting until it matters.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "rpi_report_expect_ssd_root": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Whether these Pis are expected to be running from their SSDs.",
                        "Set false for a fleet still mid-migration, so the report describes",
                        "rather than complains.",
                    ],
                ),
                "rpi_report_fail_on_drift": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Turn drift into a task failure, for CI or a scheduled check.",
                        "Default false so the report is safe to run ad hoc and always prints the",
                        "whole picture rather than stopping at the first problem.",
                    ],
                ),
            },
        ),
    }
)
