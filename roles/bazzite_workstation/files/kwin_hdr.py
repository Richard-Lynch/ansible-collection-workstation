#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Set KWin's HDR flag for the displays that can actually do HDR.

KWin stores per-display settings in ~/.config/kwinoutputconfig.json as a list of groups, each
with a `data` array holding one entry per display it has ever seen:

    {"connectorName": "HDMI-A-1", "edidHash": "a0a0...", "highDynamicRange": false, ...}

TWO REASONS THIS IS A SCRIPT RATHER THAN A TEMPLATE OR A json_query:

  1. THE FILE MUST NOT BE REGENERATED. It carries per-display state this role has no business
     owning — brightness, scale, colour profile, resolution, VRR policy, ICC path. Templating it
     would mean reproducing all of that, and getting it wrong on a display that is not currently
     plugged in and therefore cannot be checked. Only two keys are touched.

  2. ENTRIES ARE ADDRESSED BY EDID HASH, NOT BY INDEX. A config can hold two displays both
     named HDMI-A-1 — say a monitor and a TV used on the same port — because the file
     accumulates. `data[0]` is whichever was seen first, not whichever is connected now, so an
     index-based edit configures the wrong screen and looks like it worked.

HDR IS ONLY SET ON DISPLAYS WHOSE EDID DECLARES IT. Forcing the flag on a panel that cannot do
HDR makes KWin either ignore it or produce a visibly wrong picture, and neither failure points
back here.

WHY `wideColorGamut` COMES ALONG. KWin's own Display settings page enables both together, and
HDR without a wide gamut produces correct-but-flat colour. Matching what the UI does keeps the
file in a state KWin will round-trip rather than rewrite.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def edid_declares_hdr(data: bytes) -> tuple[bool, int | None]:
    """Does this EDID carry an HDR Static Metadata Data Block?

    CTA-861 extension blocks (first byte 0x02) hold a data block collection between byte 4 and
    the DTD offset in byte 2. Each block's first byte packs a 3-bit tag in the top bits and a
    length in the low 5; tag 7 means "extended tag", and extended tag 6 is HDR Static Metadata.
    The byte after that is the EOTF bitmap — bit0 SDR, bit1 traditional HDR, bit2 ST2084 (HDR10),
    bit3 HLG.
    """
    for base in range(128, len(data), 128):
        block = data[base : base + 128]
        if len(block) < 4 or block[0] != 0x02:
            continue
        end, i = block[2], 4
        while i < end and i < len(block):
            tag, length = (block[i] >> 5) & 0x07, block[i] & 0x1F
            if tag == 7 and length >= 2 and block[i + 1] == 0x06:
                return True, block[i + 2]
            i += length + 1
    return False, None


def connected_hdr_displays() -> dict[str, dict]:
    """EDID md5 -> {connector, eotf} for every CONNECTED display that declares HDR.

    Hashed with md5 because that is what KWin itself stores in `edidHash`: the live display's
    EDID hashes to the entry KWin is using.
    """
    import hashlib

    out: dict[str, dict] = {}
    for path in sorted(glob.glob("/sys/class/drm/card*-*/edid")):
        connector = os.path.basename(os.path.dirname(path))
        status_path = os.path.join(os.path.dirname(path), "status")
        try:
            if open(status_path).read().strip() != "connected":
                continue
            data = open(path, "rb").read()
        except OSError:
            continue
        if not data:
            continue
        has_hdr, eotf = edid_declares_hdr(data)
        if has_hdr:
            out[hashlib.md5(data).hexdigest()] = {"connector": connector, "eotf": eotf}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--hdr", choices=["true", "false"], required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    want = args.hdr == "true"
    messages: list[str] = []
    changes: list[str] = []

    capable = connected_hdr_displays()
    if want and not capable:
        # Not an error: a machine with no HDR display is a legitimate state, and failing here
        # would break a play whose Sunshine half is perfectly valid. But say so plainly rather
        # than reporting a silent no-op that reads as success.
        messages.append(
            "No CONNECTED display declares HDR in its EDID — nothing to enable. "
            "Sunshine may still advertise HDR, but the picture will not be HDR."
        )

    if not os.path.isfile(args.config):
        messages.append(
            f"{args.config} does not exist — KWin has not run on this machine yet. "
            "Nothing written; it is created on first desktop login."
        )
        print(
            json.dumps(
                {"changed": False, "applied": False, "messages": messages, "changes": []}, indent=2
            )
        )
        return 0

    with open(args.config, encoding="utf-8") as fh:
        doc = json.load(fh)

    groups = doc if isinstance(doc, list) else [doc]
    for group in groups:
        if not isinstance(group, dict):
            continue
        for entry in group.get("data", []):
            if not isinstance(entry, dict):
                continue
            digest = entry.get("edidHash")
            if digest not in capable:
                continue
            info = capable[digest]
            for key in ("highDynamicRange", "wideColorGamut"):
                if entry.get(key) != want:
                    changes.append(
                        f"{info['connector']} ({digest[:8]}) {key}: {entry.get(key)} -> {want}"
                    )
                    if args.apply:
                        entry[key] = want

    for digest, info in capable.items():
        messages.append(
            f"{info['connector']} declares HDR (eotf {hex(info['eotf'] or 0)}), "
            f"edidHash {digest[:8]}"
        )

    if changes and args.apply:
        # Write through a temp file in the same directory: KWin rereads this file, and a partial
        # write would leave it with no display configuration at all.
        tmp = args.config + ".iaac-tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=4)
        os.replace(tmp, args.config)
        messages.append(
            "Written. KWin reads this at session start — log out and back in, or "
            "reboot, for it to take effect in the running desktop."
        )
    elif changes:
        messages.append("(report only — re-run with bazzite_apply=true)")
    else:
        messages.append("Already in the requested state.")

    print(
        json.dumps(
            {
                "changed": bool(changes),
                "applied": bool(changes and args.apply),
                "changes": changes,
                "messages": messages,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
