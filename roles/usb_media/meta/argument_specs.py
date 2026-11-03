# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Inspect, benchmark, verify and write USB install media on macOS",
            description=[
                "Multi-entrypoint role for USB install media on macOS.",
                "Actions: list (enumerate eligible targets), inspect (vet one device),",
                "benchmark (throughput), integrity (counterfeit/failing-flash check),",
                "write (download, verify and block-copy an installer image).",
                "Every device passes the same safety gate: external, removable, whole-disk and",
                "within a size ceiling. Destructive actions require `usb_media_apply=true`.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "usb_media_action": OptionSpec(
                    type="str",
                    required=False,
                    default="list",
                    choices=[
                        "list",
                        "inspect",
                        "benchmark",
                        "integrity",
                        "random_io",
                        "retention",
                        "write",
                    ],
                    description=[
                        "Which entrypoint main.yml dispatches to.",
                        "Callers may bypass this with tasks_from instead.",
                    ],
                ),
                "usb_media_bench_mb": OptionSpec(
                    type="int",
                    required=False,
                    default=256,
                    description=[
                        "MB moved per throughput measurement. Large enough to get past a",
                        "stick's SLC write cache, which flatters short benchmarks.",
                    ],
                ),
                "usb_media_sustained_mb": OptionSpec(
                    type="int",
                    required=False,
                    default=2048,
                    description=[
                        "MB written for the SUSTAINED throughput measurement — the figure that",
                        "predicts a real image write.",
                        "Consumer flash absorbs roughly the first GB into a fast SLC cache and",
                        "then drops to its native rate; measured on one USB 3 stick,",
                        "69 MB/s at 256MB and 1GB, then 40 MB/s at 2GB.",
                        "2048 is past the cliff on every stick tested (~50s) without the ~30",
                        "minutes a full-capacity pass costs. Set 0 to skip.",
                    ],
                ),
                "usb_media_samples": OptionSpec(
                    type="int",
                    required=False,
                    default=16,
                    description="Probe points for the sparse integrity check.",
                ),
                "usb_media_full": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Integrity check writes and verifies the ENTIRE capacity.",
                        "The only mode that proves the reported size; takes two full passes.",
                    ],
                ),
                "usb_media_integrity_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=14400,
                    description=[
                        "Hard ceiling for the integrity check, in seconds (default 4 hours).",
                        "Full mode on a large slow stick genuinely needs hours.",
                    ],
                ),
                "usb_media_random_ops": OptionSpec(
                    type="int",
                    required=False,
                    default=400,
                    description="4KiB operations for the random I/O test (each written then re-read).",
                ),
                "usb_media_random_seed": OptionSpec(
                    type="int",
                    required=False,
                    default=1,
                    description=[
                        "Seed for the random offsets, so a run is reproducible and",
                        "comparable against a later run on the same device.",
                    ],
                ),
                "usb_media_retention_phase": OptionSpec(
                    type="str",
                    required=False,
                    default="wait",
                    choices=["write", "wait", "verify"],
                    description=[
                        "write: stamp blocks and exit, to be verified in a later run.",
                        "wait: write, sleep usb_media_retention_wait, then verify.",
                        "verify: compare against a state file from an earlier run.",
                        "Running write today and verify tomorrow is far stronger than wait.",
                    ],
                ),
                "usb_media_retention_wait": OptionSpec(
                    type="int",
                    required=False,
                    default=300,
                    description=[
                        "Seconds to wait in the 'wait' phase before re-reading.",
                        "Minutes catch only gross faults; a real retention test wants hours.",
                    ],
                ),
                "usb_media_retention_state": OptionSpec(
                    type="str",
                    required=False,
                    default="/var/lib/iaac-usb-media/retention-state.json",
                    description=[
                        "Where the write phase records what it wrote, so a verify run days",
                        "later can compare against it.",
                        "A ROOT-OWNED directory, deliberately NOT /tmp: the write phase runs as",
                        "root, and a plain open() in a world-writable directory can be aimed at",
                        "any file via a pre-planted symlink (arbitrary root overwrite), while a",
                        "verify would trust JSON any local user could have replaced.",
                        "Not under ~ either: with become, ~ is /var/root.",
                    ],
                ),
                "usb_media_reformat": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "After a destructive test, repartition and format the device so it is",
                        "usable again.",
                        "Defaults ON: the tests necessarily destroy the partition table, and a",
                        "raw device is one the desktop cannot use — macOS reports that state as",
                        "a misleading 'lacks the proper privileges' error in Disk Utility.",
                        "Never applied by the write entrypoint, which leaves a bootable image.",
                    ],
                ),
                "usb_media_reformat_fs": OptionSpec(
                    type="str",
                    required=False,
                    default="ExFAT",
                    description=[
                        "Filesystem for the post-test reformat. ExFAT is readable and writable",
                        "on macOS, Windows and Linux without extra drivers.",
                    ],
                ),
                "usb_media_reformat_scheme": OptionSpec(
                    type="str",
                    required=False,
                    default="GPT",
                    choices=["GPT", "MBR", "APM"],
                    description="Partition scheme for the post-test reformat.",
                ),
                "usb_media_reformat_label": OptionSpec(
                    type="str",
                    required=False,
                    default="USB",
                    description="Volume label applied by the post-test reformat.",
                ),
                "usb_media_python": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/bin/python3",
                    description="Interpreter used for the role's helper scripts.",
                ),
                "usb_media_iso_url": OptionSpec(
                    type="str",
                    required=False,
                    description="URL of the hybrid ISO to download and write.",
                ),
                "usb_media_checksum_url": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "URL of the upstream checksum file for the ISO.",
                        "Parsed for a bare 64-char SHA256 on the line naming the ISO;",
                        "the filename field itself is not trusted.",
                    ],
                ),
                "usb_media_device": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Whole-disk device node of the USB stick, e.g. /dev/disk4.",
                        "Never a partition (/dev/disk4s1) and never an /dev/rdisk node;",
                        "the raw node is derived internally for the write itself.",
                    ],
                ),
                "usb_media_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Actually write. Default false reports the pending destructive write",
                        "and stops. Does NOT bypass the safety assertions.",
                    ],
                ),
                "usb_media_verify": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Verify the downloaded ISO against the upstream checksum.",
                        "Only disable for an image with no published checksum.",
                    ],
                ),
                "usb_media_cache_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="~/.cache/iaac-install-media",
                    description="Local directory the ISO is cached in between runs.",
                ),
                "usb_media_iso_ttl_days": OptionSpec(
                    type="int",
                    required=False,
                    default=30,
                    description="Re-download the cached ISO once it is older than this.",
                ),
                "usb_media_decompress": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Decompress the downloaded file before writing it.",
                        "Raspberry Pi OS ships as .img.xz; dd-ing the COMPRESSED file produces a",
                        "card that is not bootable and gives no other symptom, so this is opt-in",
                        "per image rather than guessed from the extension.",
                        "ORDER MATTERS, and it is why this is a flag rather than a pipe: the",
                        "published checksum is of the COMPRESSED file, so the chain must be",
                        "download -> verify the archive -> decompress -> write -> read back",
                        "against the DECOMPRESSED image. Streaming `xz -d | dd` would discard",
                        "the decompressed size and hash that the post-write verification needs,",
                        "and would hide a mid-pipe failure behind dd's exit status.",
                    ],
                ),
                "usb_media_decompress_cmd": OptionSpec(
                    type="str",
                    required=False,
                    default="xz",
                    description=[
                        "Decompressor binary, resolved through PATH.",
                        "Resolved through PATH deliberately: an absolute path baked in here is",
                        "the CI-vs-dev-machine trap (a tool present on the developer's Mac and",
                        "absent on a runner, or at a different prefix under Homebrew).",
                    ],
                ),
                "usb_media_download_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=3600,
                    description="Timeout for the ISO download, in seconds. These images are ~8GB.",
                ),
                "usb_media_device_confirm": OptionSpec(
                    type="str",
                    required=False,
                    default=None,
                    description=[
                        "OPTIONAL identity token the target device must match before a",
                        "destructive action. Compared against the device's own identifiers as",
                        "diskutil reports them (serial/UUID/volume name).",
                        "WHY: the four conditions in resolve_device.yml authenticate a CLASS of",
                        "device (external, removable, whole-disk, under a size ceiling), NOT an",
                        "identity. Every card in a batch of identical SD cards passes all four,",
                        "and /dev/disk4 vs /dev/disk5 is a one-character mistake. This is the",
                        "guard for writing cards in batches.",
                        "LIMITATION, stated because a guard whose reach is misunderstood is",
                        "worse than none: for a card in a USB reader, macOS reports the",
                        "READER's serial, not the card's. Two different cards in the same reader",
                        "therefore carry the SAME token. This distinguishes devices and slots,",
                        "not cards. To distinguish cards, check their CONTENT (rpi_image_media's",
                        "verify entrypoint checks the seeded hostname).",
                        "FAIL-CLOSED: when set, an absent or unreadable device identity is a",
                        "FAILURE, never a skip. Leaving it unset preserves the existing",
                        "behaviour for callers that do not need it.",
                    ],
                ),
                "usb_media_max_device_bytes": OptionSpec(
                    type="int",
                    required=False,
                    default=137438953472,
                    description=[
                        "Upper size bound for an acceptable target device (default 128GB).",
                        "A typo selecting a large external backup drive is rejected by this.",
                    ],
                ),
                "usb_media_dd_block_size": OptionSpec(
                    type="str",
                    required=False,
                    default="4m",
                    description="Block size passed to dd. macOS dd takes the lowercase 'm' suffix.",
                ),
                "usb_media_write_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=7200,
                    description=[
                        "Hard ceiling for the async dd write, in seconds (default 2 hours).",
                        "A slow USB 2.0 stick can take well over an hour for an 8GB image.",
                    ],
                ),
                "usb_media_poll_interval": OptionSpec(
                    type="int",
                    required=False,
                    default=15,
                    description=[
                        "How often to poll the running write and report progress, in seconds.",
                    ],
                ),
                "usb_media_verify_full": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "After writing, re-read the ENTIRE image off the device and compare its",
                        "SHA256 against the source. Costs roughly one read pass (~2 min for 8GB",
                        "on USB 3).",
                        "Defaults ON: the leading-bytes check cannot see a write that failed",
                        "partway, which produces a stick that starts to boot and then fails.",
                    ],
                ),
                "usb_media_verify_published": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Also assert the device's full-image hash equals the vendor's PUBLISHED",
                        "checksum, closing the chain published -> downloaded -> written.",
                        "Opt-in: only meaningful when the image came from a source that",
                        "publishes one and usb_media_verify was on, so it is not a safe default",
                        "for a locally-supplied image.",
                        "Requires usb_media_verify_full.",
                    ],
                ),
                "usb_media_readback_bytes": OptionSpec(
                    type="int",
                    required=False,
                    default=4194304,
                    description=[
                        "How many leading bytes to read back off the device and compare",
                        "against the image, to prove the write actually landed at offset 0.",
                    ],
                ),
                "usb_media_eject": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description="Eject the device once the read-back has passed.",
                ),
                "usb_media_become": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Use become for the unmount/dd/eject steps. Writing to a raw disk",
                        "node needs root. Set false only in a test fixture.",
                    ],
                ),
                "usb_media_diskutil": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/sbin/diskutil",
                    description="Path to diskutil. Overridable so molecule can substitute a fake.",
                ),
                "usb_media_plutil": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/bin/plutil",
                    description=[
                        "Path to plutil, used to convert diskutil's plist output to JSON.",
                        "Ansible has no from_plist filter, so this conversion is required.",
                    ],
                ),
                "usb_media_dd": OptionSpec(
                    type="str",
                    required=False,
                    default="/bin/dd",
                    description="Path to dd. Overridable so molecule can substitute a fake.",
                ),
                "usb_media_shasum": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/bin/shasum",
                    description=[
                        "Path to shasum, used for the read-back comparison.",
                        "shasum ships with macOS; GNU sha256sum does not.",
                    ],
                ),
                "usb_media_sync": OptionSpec(
                    type="str",
                    required=False,
                    default="/bin/sync",
                    description="Path to sync. Overridable so molecule can substitute a fake.",
                ),
            },
        ),
    }
)
