#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cases for rpi_boot_order.py — the encoder that exists so nobody hand-writes a BOOT_ORDER.

WHY THESE CASES. Both halves of this tool were wrong on the first attempt, in opposite directions:

  * the ENCODER had to invert the caller's list, because nibbles are read right to left;
  * the TRANSPOSITION WARNING compared indices on the raw (still-reversed) string as if it read
    left to right, so it fired on every CORRECT order and stayed silent on 0xf41 — the single
    value it existed to catch.

A warning that fires on correct input gets ignored, and one that misses its own motivating case is
decoration. So every rule here is tested in BOTH directions.

Run: python3 roles/rpi_boot_media/files/test_rpi_boot_order.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rpi_boot_order import encode, explain, warnings  # noqa: E402

FAILURES = 0


def check(label: str, got, want) -> None:
    global FAILURES
    if got == want:
        print(f"  PASS  {label}")
    else:
        FAILURES += 1
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")


# --- encoding: the caller writes the order they want TRIED, first attempt first ----------------
check("ssd, card -> 0xf14 (SSD first, card fallback)", encode(["ssd", "card"]), "0xf14")
check(
    "ssd, card, http -> 0xf714 (with a network-install last resort)",
    encode(["ssd", "card", "http"]),
    "0xf714",
)
check("card, ssd -> 0xf41 (SD first; the factory default)", encode(["card", "ssd"]), "0xf41")
check("aliases resolve the same", encode(["usb", "sd"]), encode(["ssd", "card"]))
check("an explicit terminator is not doubled", encode(["ssd", "card", "stop"]), "0xe14")

# --- decoding: first attempt first --------------------------------------------------------------
check("0xf14 decodes USB-first", explain("0xf14")[0], "USB mass storage")
check("0xf41 decodes SD-first", explain("0xf41")[0], "SD card")
check("0xf714 has HTTP third", explain("0xf714")[2], "HTTP network install")
check("round-trips", explain(encode(["ssd", "card", "http"])), explain("0xf714"))


# --- warnings: each must fire on its own case AND stay silent otherwise -------------------------
def has(value: str, needle: str) -> bool:
    return any(needle in w for w in warnings(value))


# The one that motivated the whole tool: 0xf74 silently drops the rescue card.
check("0xf74 warns the card is missing", has("0xf74", "SD card is NOT"), True)
check("0xf714 does NOT warn about a missing card", has("0xf714", "SD card is NOT"), False)

# The classic transposition.
check("0xf41 warns about SD-before-USB", has("0xf41", "tried BEFORE USB"), True)
check("0xf14 does NOT warn about SD-before-USB", has("0xf14", "tried BEFORE USB"), False)
check("0xf714 does NOT warn about SD-before-USB", has("0xf714", "tried BEFORE USB"), False)

# Terminators.
check("0x14 warns there is no terminator", has("0x14", "no terminator"), True)
check("0xf14 does NOT warn about terminators", has("0xf14", "no terminator"), False)
check("0xe14 warns it ends in STOP", has("0xe14", "ends in STOP"), True)
check("0xf14 does NOT warn it ends in STOP", has("0xf14", "ends in STOP"), False)

# A correct, sensible order should be entirely quiet. If this ever fails, the warnings have
# started crying wolf and will be ignored.
check("a sensible order produces NO warnings", warnings("0xf714"), [])

print(f"\n{'ALL PASS' if not FAILURES else str(FAILURES) + ' FAILED'}")
sys.exit(1 if FAILURES else 0)
