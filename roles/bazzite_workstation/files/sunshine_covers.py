#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve cover art for Sunshine app entries from Steam's own library cache.

WHY LOCAL CACHE RATHER THAN DOWNLOADING. Steam already stores box art for every installed game
under appcache/librarycache/<appid>/. Using it means no network calls, no third-party image
host, nothing to rate-limit, and art that matches what the Steam client shows. A downloader
would be a dependency on someone else's uptime for a cosmetic feature.

WHICH IMAGE. Sunshine's grid is PORTRAIT, so `library_600x900.jpg` is the right asset;
`header.jpg` is landscape and gets letterboxed into an ugly strip. Games cached before Steam
started keeping 600x900 have only the header, which is why the fallback order matters and why a
game with neither is reported rather than silently left blank.

Idempotent: a cover already present with identical bytes is left alone, so repeated runs do not
churn the file or report changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

# Preference order. Portrait first — Sunshine renders these as tiles in a vertical grid.
CANDIDATES = ["library_600x900.jpg", "library_capsule.jpg", "header.jpg", "logo.png"]


def steam_library_cache() -> list[str]:
    """Every plausible Steam librarycache location.

    Flatpak Steam and native Steam differ, and Bazzite can have both — so this looks in all of
    them rather than assuming the layout of whichever was installed first.
    """
    home = os.path.expanduser("~")
    return [
        os.path.join(home, ".steam/steam/appcache/librarycache"),
        os.path.join(home, ".local/share/Steam/appcache/librarycache"),
        os.path.join(
            home, ".var/app/com.valvesoftware.Steam/.local/share/Steam/appcache/librarycache"
        ),
    ]


def find_art(appid: str) -> str | None:
    for root in steam_library_cache():
        base = os.path.join(root, appid)
        if not os.path.isdir(base):
            continue
        for name in CANDIDATES:
            path = os.path.join(base, name)
            if os.path.isfile(path) and os.path.getsize(path) > 1024:
                return path
    return None


def _digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--covers-dir", required=True, help="where Sunshine keeps cover art")
    ap.add_argument("--apps", required=True, help="JSON list of {name, appid} to resolve art for")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="copy the art; without this, report what would be copied",
    )
    args = ap.parse_args()

    apps = json.loads(args.apps)
    os.makedirs(args.covers_dir, exist_ok=True)

    results, changed = [], 0
    for app in apps:
        appid = str(app.get("appid", "")).strip()
        name = app.get("name", appid)
        if not appid:
            continue

        src = find_art(appid)
        if not src:
            results.append({"name": name, "appid": appid, "status": "no-art-cached", "path": None})
            continue

        dest = os.path.join(args.covers_dir, f"{appid}{os.path.splitext(src)[1]}")
        if os.path.exists(dest) and _digest(dest) == _digest(src):
            results.append(
                {
                    "name": name,
                    "appid": appid,
                    "status": "current",
                    "path": dest,
                    "source": os.path.basename(src),
                }
            )
            continue

        if args.apply:
            shutil.copy2(src, dest)
            changed += 1
        results.append(
            {
                "name": name,
                "appid": appid,
                "status": "copied" if args.apply else "would-copy",
                "path": dest,
                "source": os.path.basename(src),
            }
        )

    print(json.dumps({"covers": results, "changed": changed}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
