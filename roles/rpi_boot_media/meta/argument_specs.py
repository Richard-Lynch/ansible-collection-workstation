# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Pi 4 boot media: EEPROM order, SSD provisioning, rescue-card sealing",
            description=[
                "Owns which device a Pi 4 boots from, and the state of the two media.",
                "",
                "THE MODEL: the SD card is a near-immutable RESCUE SHELL (read-only via",
                "overlayfs, out of the normal boot path); the USB3 SSD is the read-write root",
                "that carries the workload. The board's EEPROM BOOT_ORDER prefers USB and falls",
                "back to the card. Recovery is 'boot the card, re-provision the SSD, re-run the",
                "plays' — not 'restore a backup', because these hosts are stateless by design.",
                "",
                "ORDER MATTERS AND IS NOT OBVIOUS. harden_sd MUST run while the SD is still the",
                "running root: overlayfs is enabled against the RUNNING system, so hardening",
                "after the migration hardens the SSD instead and silently destroys the primary",
                "system's persistence — with every assertion passing, because they read the file",
                "that was wrongly edited. And EEPROM must be set AFTER the SSD is verified: once",
                "the SSD's boot partition is loadable the firmware stops falling back to the",
                "card, so an interrupted provision with USB-first already set leaves a dark Pi",
                "with its rescue path preempted.",
                "",
                "GENERATE-DON'T-APPLY: every writing action reports what it would do and stops",
                "unless rpi_boot_apply=true.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "rpi_boot_action": OptionSpec(
                    type="str",
                    required=False,
                    default="probe",
                    choices=[
                        "probe",
                        "eeprom_report",
                        "eeprom",
                        "provision_ssd",
                        "harden_sd",
                        "watchdog",
                        "verify",
                        "rollback",
                    ],
                    description=[
                        "Which entrypoint main.yml dispatches to.",
                        "probe/eeprom_report/verify are read-only; the rest need rpi_boot_apply.",
                    ],
                ),
                "rpi_boot_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Actually make changes. Default false: every writing action reports its",
                        "plan and stops, because these actions repartition a disk, reflash board",
                        "firmware, or make the rescue system read-only.",
                    ],
                ),
                # --- devices: declared in inventory, never guessed -----------------------------
                "rpi_boot_ssd_by_id": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "The SSD's STABLE /dev/disk/by-id name (e.g. usb-<vendor>_<model>_<serial>-0:0).",
                        "REQUIRED with no default, deliberately. Kernel names (/dev/sda) renumber",
                        "between boots and between USB enumeration orders, so a play that trusted",
                        "one could repartition the wrong disk. And a default here would let a Pi",
                        "nobody declared proceed on a guess — for an action that destroys a disk,",
                        "absence must stop the play, not pick something plausible.",
                        "Read it from `rpi_boot_action=probe`, then declare it in host_vars.",
                    ],
                ),
                "rpi_boot_sd_by_id": OptionSpec(
                    type="str",
                    required=False,
                    default=None,
                    description=[
                        "The SD card's stable /dev/disk/by-id name (mmc-*). Optional because it",
                        "is normally discovered: on a Pi the card is the only mmc-* block device.",
                        "Declare it only where that is not true.",
                        "harden_sd ANCHORS every read, write and assertion to this device and",
                        "refuses to run if it resolves to the current root's disk — ordering is a",
                        "human-fallible guarantee; a device-identity refusal is not.",
                    ],
                ),
                # --- EEPROM --------------------------------------------------------------------
                "rpi_boot_order": OptionSpec(
                    type="str",
                    required=False,
                    default="0xf714",
                    description=[
                        "Desired EEPROM BOOT_ORDER. DO NOT HAND-WRITE THIS VALUE — generate it:",
                        "  files/rpi_boot_order.py ssd card http   ->   0xf714",
                        "Nibbles are read RIGHT TO LEFT (4=USB, 1=SD, 7=HTTP, f=restart), which",
                        "makes the format easy to misread: 0xf14 and 0xf41 differ by one",
                        "transposition and mean opposite things, and 0xf74 looks like a harmless",
                        "trim of 0xf714 while DELETING the rescue card from the boot order.",
                        "",
                        "0xf714 = try the USB SSD, then the SD card, then HTTP network install,",
                        "then loop. The first two are the fleet's normal and rescue paths; HTTP is",
                        "a last resort that covers the one case the card cannot — a dead SSD with",
                        "nobody in the building. An unreachable HTTP host simply falls through to",
                        "the restart, so it adds no dependency.",
                        "NOT THE FACTORY DEFAULT. Verified against raspberrypi/documentation:",
                        "the default when BOOT_ORDER is empty is 0xf41 — SD first, USB second.",
                        "So `eeprom` is a REAL firmware change on a new board, not the assertion",
                        "an earlier version of this text claimed. Skipping it because 'it's the",
                        "default anyway' leaves a Pi that never boots its SSD.",
                        "The trailing f matters: a Pi whose SSD is slow to enumerate on a cold",
                        "boot keeps retrying instead of sitting dark.",
                    ],
                ),
                "rpi_boot_rollback_order": OptionSpec(
                    type="str",
                    required=False,
                    default="0xf41",
                    description=[
                        "BOOT_ORDER written by the rollback action: SD card first, USB second,",
                        "then restart — which is also the Pi's FACTORY default, so a rollback",
                        "returns the board to how it shipped.",
                        "Used to send a board back to its rescue card deliberately, rather than",
                        "relying on the firmware's automatic fallback — which only covers an",
                        "UNREADABLE boot partition, not a corrupt root that panics on mount.",
                    ],
                ),
                "rpi_boot_eeprom_min_version": OptionSpec(
                    type="str",
                    required=False,
                    default="2020-09-03",
                    description=[
                        "Minimum bootloader EEPROM version for USB mass-storage boot.",
                        "A Pi that has been in a drawer since 2019 will not USB-boot AT ALL until",
                        "its bootloader is updated, and the symptom reads as 'the SSD is bad'.",
                        "Asserted before the boot order is touched so the real cause is named.",
                    ],
                ),
                # --- watchdog ------------------------------------------------------------------
                "rpi_watchdog_runtime_sec": OptionSpec(
                    type="int",
                    required=False,
                    default=14,
                    min_value=1,
                    max_value=15,
                    description=[
                        "systemd RuntimeWatchdogSec — how long the kernel may go un-petted",
                        "before the hardware resets the board.",
                        "HARD CEILING 15: the BCM watchdog cannot accept more, and values above",
                        "it have produced continuous reboot loops that are difficult to diagnose",
                        "— i.e. a misconfigured watchdog is itself a fleet-wide outage. The bound",
                        "is enforced by the generated guards, not left to a comment.",
                    ],
                ),
                "rpi_watchdog_panic_sec": OptionSpec(
                    type="int",
                    required=False,
                    default=10,
                    min_value=1,
                    description=[
                        "Seconds the kernel waits after a panic before rebooting itself",
                        "(`panic=` on the kernel command line).",
                        "A SEPARATE MECHANISM from the watchdog above, covering a failure the",
                        "watchdog cannot: a panic at root-mount happens BEFORE systemd arms the",
                        "watchdog, so RuntimeWatchdogSec can never fire for it. That is precisely",
                        "the corrupt-SSD-root case this design cares about — without `panic=` the",
                        "Pi hangs indefinitely and the firmware re-picks the same SSD forever.",
                    ],
                ),
                # --- rescue card ---------------------------------------------------------------
                "rpi_rescue_packages": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=[
                        # The overlay mechanism itself. raspi-config's enable_overlayfs does
                        # `is_installed overlayroot || apt-get install -y overlayroot` with no
                        # error check — so a failed install there leaves the cmdline token set and
                        # the card booting READ-WRITE. Declaring it means the seal never depends on
                        # an unchecked apt call made halfway through the change.
                        "overlayroot",
                        # provision_ssd decompresses the OS image with xz ON THE PI, and xz-utils
                        # is not in pi-gen's package list for Lite.
                        "xz-utils",
                        "e2fsprogs",
                        "dosfstools",
                        "parted",
                        "gdisk",
                        "rsync",
                    ],
                    description=[
                        "Tooling the rescue card must carry to be able to REPAIR or re-provision",
                        "the SSD.",
                        "Installed before the card is hardened, because afterwards its root is",
                        "read-only and nothing can ever be added — discovering the rescue system",
                        "has no fsck happens during an outage, which is the worst possible time.",
                    ],
                ),
                # --- the OS image written to the SSD -------------------------------------------
                "rpi_boot_image_url": OptionSpec(
                    type="str",
                    required=False,
                    default=None,
                    description=[
                        "URL of the Raspberry Pi OS image written to the SSD by provision_ssd.",
                        "PIN THE VERSION — do not track a 'latest' alias. The first-boot",
                        "provisioning format has changed between Pi OS releases (userconf.txt vs",
                        "custom.toml), so an unpinned image can silently change what a freshly",
                        "provisioned disk does, months after the play last worked.",
                        "Declared in inventory, not passed on the command line.",
                    ],
                ),
                "rpi_boot_image_checksum": OptionSpec(
                    type="str",
                    required=False,
                    default=None,
                    description=[
                        "SHA256 of the image at rpi_boot_image_url, checked on download.",
                        "Required alongside the URL: a truncated download produces a disk that",
                        "partially writes and may still present a loadable boot partition, which",
                        "is the failure mode that preempts the rescue card.",
                    ],
                ),
                "rpi_boot_download_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=1800,
                    description="Timeout for the OS image download, in seconds.",
                ),
                "rpi_boot_write_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=3600,
                    description=[
                        "Hard ceiling for the async image write, in seconds.",
                        "Generous because a slow USB2-negotiated bridge can take well over an",
                        "hour for a multi-GB image.",
                    ],
                ),
                "rpi_boot_reboot_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=300,
                    description="Seconds to wait for a Pi to come back after a reboot.",
                ),
                "rpi_boot_confirm": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Second confirmation for provision_ssd, which DESTROYS everything on the",
                        "target SSD. Separate from rpi_boot_apply so that 'yes, make changes' and",
                        "'yes, erase that disk' are two different statements.",
                    ],
                ),
            },
        ),
    }
)
