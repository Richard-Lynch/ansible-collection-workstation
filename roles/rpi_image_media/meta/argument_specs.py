# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Seed a written Pi card for a fully headless first boot",
            description=[
                "Runs on the CONTROLLER, not on a Pi.",
                "",
                "SCOPE: this role seeds ONLY. The usb_media role does the dangerous part — it",
                "already owns the dd, the four-condition device gate and the post-write",
                "read-back — so re-implementing any of that here would create a second source of",
                "truth for 'is it safe to write to this disk'.",
                "",
                "What it adds is the Pi-specific first-boot provisioning that turns a freshly",
                "written card into a machine Ansible can reach: a user, an SSH key, a",
                "hostname, and SSH enabled.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "rpi_image_action": OptionSpec(
                    type="str",
                    required=False,
                    default="plan",
                    choices=["plan", "seed", "verify"],
                    description=[
                        "plan   — report every file that would be written (default, writes nothing)",
                        "seed   — mount the card's boot partition and write the provisioning files",
                        "verify — re-mount and assert each seeded file is present and correct",
                    ],
                ),
                "rpi_image_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description="Actually write. Default false: report the plan and stop.",
                ),
                "rpi_image_hostname": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "Hostname seeded onto the card — and the CARD-IDENTITY marker.",
                        "REQUIRED with no default: a card seeded with the wrong name produces a",
                        "hostname collision in DNS and monitoring that nothing else detects, and",
                        "a default would let an undeclared caller create one silently.",
                        "Also what makes a card identifiable afterwards, which is the only check",
                        "that can tell two otherwise-identical cards apart.",
                    ],
                ),
                "rpi_image_user": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "First-boot username. REQUIRED with no default — a default username is",
                        "site config wearing a default's clothing, and makes the role silently",
                        "wrong for every other caller.",
                    ],
                ),
                "rpi_image_password_hash": OptionSpec(
                    type="str",
                    required=True,
                    no_log=True,
                    description=[
                        "The user's password as a CRYPT HASH, never plaintext.",
                        "Resolve it at run time from a secret store (for example 1Password via",
                        "richard_lynch.common.onepassword_cached). Neither the repo nor the card",
                        "should ever hold the plaintext.",
                        "no_log because a validation failure would otherwise echo it into the",
                        "run log and CI output.",
                    ],
                ),
                "rpi_image_authorized_key": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "The SSH PUBLIC key seeded into the user's authorized_keys.",
                        "PUBLIC only. Nothing private-key-shaped may ever be seeded onto a card:",
                        "an SD card is readable by anyone who physically takes it, and the fact",
                        "that a card carries only a hash and a public key is what makes an",
                        "SD-based rescue system acceptable at all. The seed step refuses a value",
                        "that looks like a private key.",
                    ],
                ),
                "rpi_image_boot_mount": OptionSpec(
                    type="str",
                    required=False,
                    default="/Volumes/bootfs",
                    description=[
                        "Where the card's FAT boot partition is mounted on the controller.",
                        "macOS automounts a freshly written Pi image here by its volume label.",
                    ],
                ),
                "rpi_image_wifi_ssid": OptionSpec(
                    type="str",
                    required=False,
                    default=None,
                    description=[
                        "Optional WiFi SSID for a Pi that genuinely cannot be wired.",
                        "Ethernet is the expected uplink.",
                    ],
                ),
                "rpi_image_wifi_country": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "WiFi regulatory domain (ISO 3166 alpha-2, e.g. 'US'). No default: where",
                        "a device is used is the caller's to say. REQUIRED WHENEVER WIFI IS USED: without a",
                        "country code the radio comes up rfkill-blocked on first boot, so a",
                        "headless Pi never appears on the network and nothing on it says why.",
                    ],
                ),
            },
        ),
    }
)
