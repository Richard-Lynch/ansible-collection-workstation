# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Per-Pi OS baseline: identity, packages, USB quirks, cgroups",
            description=[
                "The 'make this Pi a managed host' role, separate from boot-media",
                "concerns (which belong to rpi_boot_media).",
                "",
                "Covers hostname, timekeeping, journald caps, the memory cgroup Docker needs,",
                "and the USB-SATA quirks that decide whether the SSD is reliable at all.",
                "",
                "DOES NOT deploy services. Docker, log shipping, alert rules and anything fleet-level",
                "belong to other roles — this one stops at the OS.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "rpi_host_action": OptionSpec(
                    type="str",
                    required=False,
                    default="probe",
                    choices=["probe", "baseline", "usb_quirks", "cgroups", "health_report", "all"],
                    description=[
                        "Which entrypoint main.yml dispatches to.",
                        "probe and health_report are read-only; the rest need rpi_host_apply.",
                        "`all` runs baseline + usb_quirks + cgroups.",
                    ],
                ),
                "rpi_host_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description="Actually make changes. Default false: report the plan and stop.",
                ),
                "rpi_soc_serial": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "This board's SoC serial, from /proc/cpuinfo — the BOARD-IDENTITY anchor.",
                        "REQUIRED with no default. Nothing else ties a hostname to a physical",
                        "board: two cards seeded with the same hostname in two boards produce",
                        "distinct MACs and addresses (so the reservations quietly work) but a",
                        "colliding name in DNS and monitoring, with nothing to detect it.",
                        "Asserted against the live board, so a swapped card is caught rather",
                        "than silently accepted.",
                        "Read it from rpi_boot_action=probe, then declare it in host_vars.",
                    ],
                ),
                "rpi_usb_quirks": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=[],
                    description=[
                        "usb-storage quirk entries, as VID:PID:u — `u` meaning 'ignore UAS'.",
                        "Several widely sold USB3-SATA bridges (JMicron and ASMedia among them)",
                        "implement UAS incorrectly on the Pi, producing anything from poor",
                        "throughput to data corruption under load.",
                        "EMPTY BY DEFAULT AND DELIBERATELY REACTIVE: blanket-disabling UAS costs",
                        "real throughput on adapters that are fine. Probe reports each bridge's",
                        "VID:PID; add an entry here only when a specific adapter misbehaves.",
                        "Estate config — declared in inventory, never guessed by the role.",
                    ],
                ),
                "rpi_cgroup_memory": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Enable the kernel memory cgroup controller.",
                        "WITHOUT IT, `docker run --memory=`, systemd's MemoryMax= and k3s pod",
                        "limits are all ACCEPTED AND SILENTLY UNENFORCED — the kernel has nowhere",
                        "to write the limit. Every layer reports success; nothing is limited.",
                        "Verification must read /proc/cmdline and cgroup.controllers, never",
                        "cmdline.txt: the firmware injects cgroup_disable=memory, which never",
                        "appears in that file, so a config-file check cannot fail.",
                    ],
                ),
                "rpi_journald_max_use": OptionSpec(
                    type="str",
                    required=False,
                    default="200M",
                    description=[
                        "Cap on journald's on-disk size. Bounded because an unbounded journal on",
                        "a small root filesystem is a slow-motion disk-full outage.",
                    ],
                ),
                "rpi_timezone": OptionSpec(
                    type="str",
                    required=False,
                    default="Etc/UTC",
                    description=[
                        "System timezone. UTC by default — a generic, correct-for-any-caller",
                        "value; a fleet wanting local time declares it in inventory.",
                    ],
                ),
                "rpi_host_packages": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=[
                        "ca-certificates",
                        "curl",
                        "gnupg",
                        "python3",
                        "smartmontools",
                        # REQUIRED for rpi_unattended_security to mean anything. Raspberry Pi OS
                        # Lite does not ship it, and apt.systemd.daily silently no-ops when the
                        # binary is absent — so the APT::Periodic flag we write would drive
                        # nothing at all while the play reported "unattended security updates on".
                        "unattended-upgrades",
                    ],
                    description=[
                        "Baseline packages every Pi gets. Generic: nothing site-specific, and",
                        "nothing service-specific — services install their own dependencies.",
                    ],
                ),
                "rpi_unattended_security": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Apply SECURITY updates automatically (never full upgrades).",
                        "Sensible for a stateless fleet: a rebuild is cheap, an unpatched box is",
                        "not. Full upgrades stay manual because an unattended kernel change on a",
                        "USB-booted Pi is exactly the thing that should be observed.",
                    ],
                ),
            },
        ),
    }
)
