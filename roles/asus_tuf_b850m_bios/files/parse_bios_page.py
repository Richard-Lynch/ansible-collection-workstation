#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract the BIOS version table from ASUS's support page.

Called by this role's tasks/list_versions.yml.

HOW THIS WAS ESTABLISHED, because it is not obvious and the obvious approaches all fail:

  * The support page is a Nuxt app. Fetching the trailing-slash URL
    (.../helpdesk_bios/) returns a ~17KB client-rendered shell with no data in it.
  * ASUS's JSON endpoint www.asus.com/support/api/product.asmx/GetPDBIOS returns real JSON but
    IGNORES the product id — every call returns the same hardcoded default board
    (ASUS_D701MER), whichever board is requested. Verified against pdid, ProductId, productId,
    m1id, M1Id and pdhashedid, with and without pdlevel. Building on it would silently serve
    another board's firmware.
  * Watching the page's own network traffic in a real browser settled it: there is NO XHR for
    BIOS data at all. Nuxt renders it server-side.

So the data IS available without JavaScript — but only from the `?model2Name=` form of the URL,
which returns the full ~566KB server-rendered payload. That single query parameter is the whole
difference between "no data" and "all of it".

WHAT IS PARSED, and what deliberately is not. Version, release date, size, SHA-256 and the
release notes all come from the page. Download URLs do NOT: they are constructed client-side and
appear nowhere in the payload, so they stay pinned in the role where they have been verified by
HTTP HEAD. Guessing a URL from a pattern is how you fetch the wrong file.

Class names in the markup are per-build hashes (e.g. __fileSize___5R4Bx), so every selector here
anchors on the STABLE prefix before the hash. If ASUS restructures the page this returns zero
rows rather than wrong ones — and the caller asserts on the count.

Always exits 0 with JSON on stdout; an empty list is a legitimate result the caller must handle.
"""

import json
import re
import sys
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse(html: str):
    # Each release is one "boxContent" block. Splitting on the stable class prefix keeps this
    # working across builds, where the trailing hash changes.
    blocks = re.split(r"__boxContent___", html)[1:]
    out = []
    for b in blocks:
        version = re.search(r">Version (\d{3,4})<", b)
        sha = re.search(r"SHA-256\s*[：:]\s*([0-9A-Fa-f]{64})", b)
        if not (version and sha):
            continue
        size = re.search(r"__fileSize___[^>]*>([^<]+)<", b)
        date = re.search(r"__releaseDate___[^>]*>([^<]+)<", b)
        # Release notes carry the FlashBack filename and any rollback warning, both of which
        # matter operationally.
        notes = re.search(r'"((?:1\.|Update|Improve|New |First)[^"]{10,600})"', b)
        note_text = notes.group(1).strip() if notes else ""
        out.append(
            {
                "version": version.group(1),
                # "Beta" appears as a badge within the block; scoped to the block's head so a
                # mention in a later release note cannot mislabel this one.
                "beta": bool(re.search(r"\bBeta\b", b[:2000])),
                "released": (date.group(1).replace("/", "-") if date else ""),
                "size": size.group(1).strip() if size else "",
                "sha256": sha.group(1).upper(),
                "notes": note_text,
                # Surfaced explicitly: several versions cannot be rolled back, which makes flashing
                # them a one-way door.
                "no_rollback": bool(re.search(r"cannot be roll", b, re.I)),
                # The name FlashBack expects after BIOSRenamer, when the notes state it.
                "flashback_name": (
                    re.search(r"\(([A-Z0-9]+\.CAP)\)", b).group(1)
                    if re.search(r"\(([A-Z0-9]+\.CAP)\)", b)
                    else ""
                ),
            }
        )
    return out


def main() -> int:
    url = sys.argv[1]
    try:
        html = fetch(url)
    except Exception as exc:  # noqa: BLE001 - the caller wants the reason, not a traceback
        print(json.dumps({"ok": False, "error": str(exc), "versions": []}))
        return 0

    versions = parse(html)
    print(
        json.dumps(
            {
                "ok": bool(versions),
                "count": len(versions),
                "page_bytes": len(html),
                "versions": versions,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
