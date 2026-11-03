#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Report the negotiated USB link speed for a given /dev/diskN.

Called from the usb_media role (health entrypoints).

WHY THIS EXISTS. `diskutil` knows a device is on USB but not at what LINK SPEED it negotiated.
That single fact is what turns "the write is slow" into the actionable "this USB 3.x stick
negotiated high_speed, so it is in a 2.0 port" — a 4x difference in write time, and the most
common reason an 8GB image takes 20 minutes instead of 5.

HOW THE JOIN IS MADE, and why not the obvious way. The tempting source is
`system_profiler SPUSBDataType`, but it keys everything by USB product NAME, and it is common
to have two identical sticks connected at once — a name
match picks an arbitrary one of a pair and confidently reports the wrong device's speed, which is
worse than reporting nothing. `diskutil info` exposes no serial number to disambiguate with
(verified: its keys carry IORegistryEntryName but no serial).

So the join goes through IOKit instead: each IOUSBHostDevice node carries `Device Speed`, and the
IOMedia nodes beneath it carry `BSD Name`. Walking the subtree of each USB device and collecting
the BSD names under it maps diskN -> that device's speed with no name matching at all, and no
ambiguity between identical sticks.

The tree is arbitrarily nested (controller -> hub -> hub -> device -> media), so both the search
for USB devices and the collection of BSD names beneath one are recursive; a fixed-depth walk
would silently miss a stick behind a hub.

Always exits 0 with JSON on stdout. An unmatched device yields nulls rather than an error:
"speed unknown" is a legitimate outcome and must not fail the health check.
"""

import json
import plistlib
import subprocess
import sys

# IOKit's Device Speed enum. Values are stable across macOS releases and documented in
# IOUSBFamily; the labels carry the practical throughput ceiling because that is the number
# someone reading this report is actually trying to work out.
SPEEDS = {
    0: ("low_speed", "1.5 Mb/s (USB 1.0)"),
    1: ("full_speed", "12 Mb/s (USB 1.1)"),
    2: ("high_speed", "480 Mb/s (USB 2.0) — ~35 MB/s ceiling"),
    3: ("super_speed", "5 Gb/s (USB 3.0)"),
    4: ("super_speed_plus", "10 Gb/s (USB 3.1)"),
    5: ("super_speed_plus", "20 Gb/s (USB 3.2)"),
}


def collect_bsd_names(node, found):
    """Every BSD Name anywhere beneath this IOKit node."""
    if isinstance(node, dict):
        name = node.get("BSD Name")
        if name:
            found.add(name)
        for child in node.get("IORegistryEntryChildren", []):
            collect_bsd_names(child, found)


def search(nodes, want_disk, results):
    for node in nodes or []:
        speed = node.get("Device Speed")
        if speed is not None:
            beneath = set()
            collect_bsd_names(node, beneath)
            if want_disk in beneath:
                label, detail = SPEEDS.get(speed, (f"unknown({speed})", ""))
                results.append(
                    {
                        "speed": label,
                        "speed_detail": detail,
                        "name": (node.get("USB Product Name") or node.get("IORegistryEntryName")),
                        "vendor": node.get("USB Vendor Name"),
                        "serial": node.get("USB Serial Number"),
                    }
                )
        search(node.get("IORegistryEntryChildren", []), want_disk, results)


def main() -> int:
    # Accepts /dev/disk4, /dev/rdisk4, or bare disk4.
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    disk = raw.rsplit("/", 1)[-1].replace("rdisk", "disk")

    unknown = {"speed": None, "speed_detail": "", "name": None, "vendor": None, "serial": None}

    try:
        out = subprocess.run(
            ["ioreg", "-a", "-c", "IOUSBHostDevice", "-r", "-l", "-w0"],
            capture_output=True,
            timeout=60,
            check=False,
        ).stdout
        tree = plistlib.loads(out) if out else []
    except (subprocess.SubprocessError, OSError, plistlib.InvalidFileException, ValueError):
        print(json.dumps(unknown))
        return 0

    results = []
    search(tree, disk, results)
    print(json.dumps(results[0] if results else unknown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
