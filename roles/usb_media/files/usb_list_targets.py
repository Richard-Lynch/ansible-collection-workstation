#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Enumerate attached disks and say which are safe targets for install media.

Called from the usb_media role (list entrypoint).

WHY THIS EXISTS RATHER THAN `diskutil list`. The raw output is a wall of partition tables in
which the one fact that matters — is this the boot disk or a USB stick — is not stated anywhere.
Picking the wrong line there is how people `dd` over their own SSD, and /dev/disk4 vs /dev/disk2
is one character. So this evaluates each whole disk against the SAME four conditions the write
path enforces (external, removable, whole-disk, within a size window) and prints the verdict
next to each device, with the reason when it is refused.

Device identifiers are NOT stable. macOS renumbers them as devices come and go — /dev/disk4 can be
a 64GB stick at one point and a different 32GB stick twenty minutes later, after unrelated sticks
are unplugged. That is exactly why this exists as a thing you run
immediately before writing, rather than a list you write down once.

The mount points and volume names of each device's partitions are shown too, since "which stick
is this physically" is usually answered by recognising a volume name, and writing to a stick you
still have files on is the other common regret.

Always exits 0 with JSON on stdout: a machine with no eligible devices is a normal answer, not
an error, and the play decides what to do about it.
"""

import json
import plistlib
import subprocess
import sys

# Same ceiling as usb_install_media's default: a device larger than this is far more likely to be
# a backup drive selected by a typo than a USB stick.
DEFAULT_MAX_BYTES = 137438953472  # 128 GB


def diskutil_plist(*args):
    """Run diskutil and parse its plist output, RAISING on failure.

    `-plist` goes BEFORE the operand, not after: `diskutil info -plist /dev/disk4` works and
    `diskutil info /dev/disk4 -plist` is a usage error. The first version of this got it backwards
    and, worse, swallowed the resulting empty output into `{}` — so every device came back with no
    size and no properties and was reported as "0 GB, refused: internal disk", which looks like a
    finding rather than the bug it was. An empty parse must raise, not degrade into a plausible
    wrong answer.
    """
    proc = subprocess.run(
        ["/usr/sbin/diskutil", args[0], "-plist", *args[1:]],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"diskutil {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.decode(errors='replace').strip()[:200]}"
        )
    return plistlib.loads(proc.stdout)


def link_speeds():
    """Map BSD disk name -> USB link speed, via IOKit.

    Same join as usb_link_speed.py: each IOUSBHostDevice carries Device Speed, and the IOMedia
    nodes beneath it carry BSD Name. Matching on the tree rather than on product name is what
    keeps two identical sticks distinguishable.
    """
    speeds = {}
    try:
        out = subprocess.run(
            ["ioreg", "-a", "-c", "IOUSBHostDevice", "-r", "-l", "-w0"],
            capture_output=True,
            timeout=60,
            check=False,
        ).stdout
        tree = plistlib.loads(out) if out else []
    except Exception:
        return speeds

    names = {
        0: "low",
        1: "full(USB1.1)",
        2: "high(USB2.0)",
        3: "super(USB3.0)",
        4: "super+(USB3.1)",
        5: "super+(USB3.2)",
    }

    def collect(node, found):
        if isinstance(node, dict):
            if node.get("BSD Name"):
                found.add(node["BSD Name"])
            for child in node.get("IORegistryEntryChildren", []):
                collect(child, found)

    def walk(nodes):
        for node in nodes or []:
            speed = node.get("Device Speed")
            if speed is not None:
                beneath = set()
                collect(node, beneath)
                for bsd in beneath:
                    speeds[bsd] = names.get(speed, str(speed))
            walk(node.get("IORegistryEntryChildren", []))

    walk(tree)
    return speeds


def evaluate(info, max_bytes):
    """The four conditions the write path enforces, evaluated identically here.

    Kept deliberately in lockstep with usb_install_media's gate: a device this reports as
    ELIGIBLE must be one the role will actually accept, or the listing is worse than useless.
    Defaults are the SAFE direction — an absent key blocks rather than allows.
    """
    reasons = []
    if info.get("Internal", True):
        reasons.append("internal disk")
    removable = info.get("Removable", info.get("RemovableMedia", False))
    if not removable:
        reasons.append("not removable")
    if not info.get("WholeDisk", False):
        reasons.append("not a whole disk (it is a partition)")
    size = info.get("TotalSize") or 0
    if size <= 0:
        reasons.append("no readable size")
    elif size > max_bytes:
        reasons.append(
            f"larger than the {max_bytes / 1e9:.0f} GB ceiling — looks like a drive, not a stick"
        )
    return reasons


def main() -> int:
    max_bytes = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MAX_BYTES

    try:
        listing = diskutil_plist("list")
    except Exception as exc:
        # Non-zero exit: the play must not treat "diskutil is broken" as "no devices attached".
        print(json.dumps({"error": str(exc), "devices": [], "eligible": []}))
        return 1

    speeds = link_speeds()
    devices = []

    for disk in listing.get("AllDisksAndPartitions", []):
        ident = disk.get("DeviceIdentifier")
        if not ident:
            continue
        try:
            info = diskutil_plist("info", f"/dev/{ident}")
        except Exception as exc:
            # Reported as its own row rather than dropped: a device that cannot be interrogated is
            # a fact the caller needs, and silently omitting it would make the list look complete
            # when it is not.
            devices.append(
                {
                    "device": f"/dev/{ident}",
                    "model": "UNREADABLE",
                    "size": 0,
                    "size_gb": 0,
                    "protocol": "?",
                    "link": speeds.get(ident, ""),
                    "internal": True,
                    "removable": False,
                    "whole": False,
                    "eligible": False,
                    "reasons": [f"could not read device info: {exc}"],
                    "volumes": [],
                }
            )
            continue

        size = info.get("TotalSize") or 0
        reasons = evaluate(info, max_bytes)

        # Partition/volume detail: what is actually ON this thing. The commonest regret is
        # writing over a stick that still had files on it, and a volume name is how a human
        # recognises that before it happens.
        volumes = []
        for part in disk.get("Partitions", []) or []:
            volumes.append(
                {
                    "id": part.get("DeviceIdentifier"),
                    "name": part.get("VolumeName"),
                    "mount": part.get("MountPoint"),
                    "size": part.get("Size"),
                }
            )
        for vol in disk.get("APFSVolumes", []) or []:
            volumes.append(
                {
                    "id": vol.get("DeviceIdentifier"),
                    "name": vol.get("VolumeName"),
                    "mount": vol.get("MountPoint"),
                    "size": vol.get("Size"),
                }
            )

        devices.append(
            {
                "device": f"/dev/{ident}",
                "model": info.get("MediaName") or "unknown",
                "size": size,
                "size_gb": round(size / 1e9, 1) if size else 0,
                "protocol": info.get("BusProtocol") or "?",
                "link": speeds.get(ident, ""),
                "internal": bool(info.get("Internal", True)),
                "removable": bool(info.get("Removable", info.get("RemovableMedia", False))),
                "whole": bool(info.get("WholeDisk", False)),
                "eligible": not reasons,
                "reasons": reasons,
                "volumes": volumes,
            }
        )

    devices.sort(key=lambda d: (not d["eligible"], d["device"]))
    print(
        json.dumps(
            {
                "devices": devices,
                "eligible": [d["device"] for d in devices if d["eligible"]],
                "max_bytes": max_bytes,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
