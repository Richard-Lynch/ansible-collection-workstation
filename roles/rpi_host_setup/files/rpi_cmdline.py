#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Idempotently set or remove tokens in a Raspberry Pi cmdline.txt.

WHY A SCRIPT. /boot/firmware/cmdline.txt is a SINGLE LINE of space-separated tokens. Every naive
approach to editing it has a specific failure:

  * lineinfile appends a SECOND line, which the firmware silently ignores — so the change appears
    to have been made and has no effect whatsoever.
  * A sed one-liner per token, run from a task loop, rewrites the file repeatedly and reports
    `changed` every time, so nothing downstream can tell a real change from a no-op.
  * Replacing a token with a regex risks matching a SUBSTRING of another token: `panic=10` inside
    `nopanic=10`, or `root=` inside `rootwait`.

So: parse into tokens, operate on whole tokens, write once, and report whether anything actually
changed. Exits 0 always (unless the file is unreadable); the CHANGED/UNCHANGED verdict is on
stdout so the caller's changed_when can key off it rather than off a rewrite having occurred.

Usage:
  rpi_cmdline.py --file /boot/firmware/cmdline.txt \
      --set cgroup_enable=memory --set cgroup_memory=1 \
      --remove cgroup_disable --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def token_key(token: str) -> str:
    """The part of a token used for identity: everything before the first '='.

    Tokens are either bare flags (`quiet`, `rootwait`) or key=value (`root=PARTUUID=...`). Note
    the value itself may contain '=' — `root=PARTUUID=abc` splits into key `root` and value
    `PARTUUID=abc` — so the split must be bounded to the FIRST separator.
    """
    return token.split("=", 1)[0]


def apply_changes(tokens: list[str], sets: list[str], removes: list[str]) -> list[str]:
    out: list[str] = []
    set_keys = {token_key(s): s for s in sets}
    remove_keys = set(removes)
    seen: set[str] = set()

    for tok in tokens:
        key = token_key(tok)
        if key in remove_keys:
            continue  # dropped entirely
        if key in set_keys:
            if key in seen:
                continue  # collapse a duplicate that was already there
            out.append(set_keys[key])
            seen.add(key)
            continue
        out.append(tok)

    # Anything requested but not already present is appended, in the order given.
    for key, value in set_keys.items():
        if key not in seen:
            out.append(value)

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        dest="sets",
        help="token to ensure is present, e.g. cgroup_enable=memory",
    )
    ap.add_argument(
        "--remove",
        action="append",
        default=[],
        dest="removes",
        help="token KEY to ensure is absent, e.g. cgroup_disable",
    )
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    args = ap.parse_args()

    path = Path(args.file)
    try:
        original = path.read_text()
    except OSError as exc:
        print(f"ERROR cannot read {path}: {exc}", file=sys.stderr)
        return 1

    # The file is one line; join defensively in case a previous bad edit left several.
    tokens = original.split()
    updated = apply_changes(tokens, args.sets, args.removes)

    if updated == tokens:
        print("UNCHANGED")
        print(" ".join(tokens))
        return 0

    if not args.check:
        # Single trailing newline, single line of content — the format the firmware expects.
        path.write_text(" ".join(updated) + "\n")

    print("CHANGED")
    print(" ".join(updated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
