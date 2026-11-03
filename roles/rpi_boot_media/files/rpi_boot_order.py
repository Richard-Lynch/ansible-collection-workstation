#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and explain a Raspberry Pi BOOT_ORDER from readable names.

WHY THIS EXISTS. BOOT_ORDER is a hex string whose nibbles are read RIGHT TO LEFT, which makes it
almost perfectly designed to be got wrong: `0xf14` and `0xf41` differ by one transposed character
and mean opposite things, and `0xf74` looks like a harmless tweak of `0xf714` while actually
DELETING the SD card from the boot order.

That last one looks like an improvement and removes the rescue path the whole design rests on;
only decoding the value into words makes it visible. So: nobody should hand-write these.

    rpi_boot_order.py ssd card http
    -> 0xf714

    rpi_boot_order.py --explain 0xf74
    -> 0xf74  =  USB mass storage (SSD)  ->  HTTP network install  ->  RESTART
       WARNING: the SD card is not in this boot order.

The trailing RESTART (`f`) is appended automatically unless you ask for a different terminator,
because a Pi whose SSD is slow to enumerate on a cold boot should keep retrying rather than sit
dark — and because ending on STOP (`e`) is a decision, not a default.
"""

from __future__ import annotations

import argparse
import sys

# Nibble values, per the Raspberry Pi bootloader documentation.
# Names are ours; several aliases each so the caller can write what they mean.
MODES: dict[str, tuple[str, str]] = {
    # alias           nibble  human description
    "sd": ("1", "SD card"),
    "card": ("1", "SD card"),
    "sdcard": ("1", "SD card"),
    "rescue": ("1", "SD card"),
    "network": ("2", "network boot (TFTP)"),
    "tftp": ("2", "network boot (TFTP)"),
    "netboot": ("2", "network boot (TFTP)"),
    "rpiboot": ("3", "RPIBOOT (USB device mode)"),
    "usb": ("4", "USB mass storage"),
    "ssd": ("4", "USB mass storage"),
    "usb-msd": ("4", "USB mass storage"),
    "bcm-usb": ("5", "BCM-USB-MSD"),
    "nvme": ("6", "NVMe"),
    "http": ("7", "HTTP network install"),
    "net-install": ("7", "HTTP network install"),
    "restart": ("f", "RESTART the sequence (loop)"),
    "loop": ("f", "RESTART the sequence (loop)"),
    "stop": ("e", "STOP (halt with an error pattern)"),
}

# For --explain, and for the warnings below.
NIBBLE_NAMES: dict[str, str] = {
    "0": "SD CARD DETECT (wait for a card)",
    "1": "SD card",
    "2": "network boot (TFTP)",
    "3": "RPIBOOT (USB device mode)",
    "4": "USB mass storage",
    "5": "BCM-USB-MSD",
    "6": "NVMe",
    "7": "HTTP network install",
    "e": "STOP (halt with an error pattern)",
    "f": "RESTART the sequence (loop)",
}

TERMINATORS = {"f", "e"}


def encode(names: list[str]) -> str:
    """Turn ['ssd', 'card', 'http'] into '0xf714'.

    The list is given in the order the firmware should TRY them — first attempt first, which is
    how a human thinks about it. Because nibbles are read right to left, the string is built in
    reverse. That inversion is the entire reason this function exists.
    """
    nibbles = []
    for name in names:
        key = name.strip().lower()
        if key not in MODES:
            raise SystemExit(f"unknown boot mode '{name}'. Known: {', '.join(sorted(set(MODES)))}")
        nibbles.append(MODES[key][0])

    if not nibbles:
        raise SystemExit("no boot modes given")

    # Append the loop terminator unless the caller already ended with one.
    if nibbles[-1] not in TERMINATORS:
        nibbles.append("f")

    # RIGHT TO LEFT: the first mode to try must be the LEAST significant nibble.
    return "0x" + "".join(reversed(nibbles))


def explain(value: str) -> list[str]:
    """Decode a BOOT_ORDER into the order the firmware actually tries, first attempt first."""
    digits = value.strip().lower().removeprefix("0x")
    return [NIBBLE_NAMES.get(d, f"unknown ({d})") for d in reversed(digits)]


def warnings(value: str) -> list[str]:
    """Things about a boot order that are legal, and probably not what was meant."""
    digits = value.strip().lower().removeprefix("0x")
    out = []
    if "1" not in digits:
        out.append(
            "the SD card is NOT in this boot order — a board whose primary medium fails has no "
            "local rescue path and will need someone physically present"
        )
    if not (set(digits) & TERMINATORS):
        out.append("no terminator: this order neither loops (f) nor stops (e). Add one explicitly")
    # startswith, NOT endswith: `digits` is still right-to-left, so the LAST mode tried is the
    # FIRST character. `0xe14` is USB -> SD -> STOP, and its terminator is the leading `e`.
    # Third ordering bug in this one small file — which is why it has a test suite.
    if digits.startswith("e"):
        out.append(
            "ends in STOP: a board that fails every mode will sit dark rather than retrying. "
            "Deliberate for a bench, wrong for a machine in a cupboard"
        )
    # THE CLASSIC TRANSPOSITION. Remember `digits` is the RAW string, still right-to-left: the
    # first mode tried is the LAST character. So "USB is tried before the card" means 4 appears
    # LATER in the string than 1 — and the warning fires when that is not the case.
    #
    # The first version of this check compared index() on the raw string as if it read
    # left-to-right, so it fired on every CORRECT order and stayed silent on 0xf41, the one value
    # it existed to catch. Caught by running it; hence the fixtures in the test below.
    if "1" in digits and "4" in digits and digits.index("4") < digits.index("1"):
        out.append(
            "the SD card is tried BEFORE USB — every boot then comes off the card. If you meant "
            "USB-first, the nibbles are transposed (this is the 0xf14 vs 0xf41 mistake)"
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build or explain a Raspberry Pi BOOT_ORDER.",
        epilog="e.g. rpi_boot_order.py ssd card http   ->   0xf714",
    )
    ap.add_argument("modes", nargs="*", help="boot modes, in the order to TRY them")
    ap.add_argument("--explain", metavar="VALUE", help="decode an existing BOOT_ORDER instead")
    args = ap.parse_args()

    if args.explain:
        value = args.explain
    elif args.modes:
        value = encode(args.modes)
    else:
        ap.print_help()
        return 2

    print(value)
    for i, step in enumerate(explain(value), 1):
        print(f"  {i}. {step}")
    for w in warnings(value):
        print(f"  WARNING: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
