#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Random-offset small-block I/O test for USB storage.

Called from the usb_media role's random_io entrypoint.

WHY THIS EXISTS AND WHAT IT ADDS. Sequential `dd` measures the one access pattern flash is best
at. A controller can post a perfectly good 40 MB/s sequential figure and still stall badly on
scattered small writes, because every small write to a fresh region forces a read-modify-write of
a much larger erase block. That read-modify-write amplification is invisible to a sequential
benchmark and is the difference between a stick that feels fine and one that takes minutes to
copy a directory of small files.

It is also a health signal rather than only a speed one: a device whose random-write latency has
a very long tail is usually one whose controller is working hard to find usable erase blocks —
i.e. worn flash. A single slow outlier means nothing; a p99 an order of magnitude above the
median is worth knowing about.

WHAT IT DOES NOT PROVE. Nothing here is a substitute for the full-capacity verify: this touches a
small, scattered fraction of the device by design. And a good result on an ISO-writing workload
is not very informative — a hybrid ISO write is purely sequential. This matters if the stick will
ever hold a filesystem with many small files.

DESTRUCTIVE: it writes to the raw device. Offsets are chosen with a SEEDED generator so a run is
reproducible and can be compared against a later one on the same device.

Always exits 0 with JSON on stdout; a device that errors mid-test reports what it managed rather
than dying, because a partial result plus the error is more useful than a traceback.
"""

import json
import os
import random
import statistics
import sys
import time

# 4 KiB: the filesystem block size that dominates real small-file workloads, and small enough
# relative to a flash erase block (typically 128KiB-4MiB) to actually provoke read-modify-write.
BLOCK = 4096
MAGIC = b"IAAC-RND"


def make_block(offset: int) -> bytes:
    head = b"%s off=%016d " % (MAGIC, offset)
    filler = bytes((offset // BLOCK + i) % 251 for i in range(64))
    body = (filler * (BLOCK // len(filler) + 1))[: BLOCK - len(head)]
    return head + body


def percentile(values, pct):
    """Nearest-rank percentile. Avoids a numpy dependency for a handful of samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * len(ordered) + 0.5)) - 1))
    return ordered[index]


def main() -> int:
    device = sys.argv[1]
    total_size = int(sys.argv[2])
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1

    usable_blocks = (total_size - BLOCK) // BLOCK
    if usable_blocks <= 0:
        print(json.dumps({"ok": False, "report": ["Device too small to test."]}))
        return 0

    rng = random.Random(seed)
    offsets = [rng.randrange(usable_blocks) * BLOCK for _i in range(count)]

    write_ms, read_ms, errors, mismatches = [], [], [], 0

    # --- random write pass, timing each operation individually ---
    # O_SYNC so each write reaches the device rather than being absorbed by the page cache and
    # timed as memory speed. Without it this measures macOS, not the stick.
    try:
        fd = os.open(device, os.O_WRONLY | os.O_SYNC)
    except OSError as exc:
        print(json.dumps({"ok": False, "report": [f"Cannot open {device} for writing: {exc}"]}))
        return 0
    try:
        for off in offsets:
            block = make_block(off)
            start = time.perf_counter()
            try:
                os.lseek(fd, off, os.SEEK_SET)
                os.write(fd, block)
            except OSError as exc:
                errors.append(f"write at {off}: {exc.strerror}")
                continue
            write_ms.append((time.perf_counter() - start) * 1000)
    finally:
        os.close(fd)

    # --- random read pass, verifying content as well as timing ---
    # Reopened so the page cache cannot answer, and read in a DIFFERENT random order than it was
    # written: reading back in write order would let any sequential prefetch flatter the result.
    read_order = list(offsets)
    rng.shuffle(read_order)
    try:
        fd = os.open(device, os.O_RDONLY)
    except OSError as exc:
        print(json.dumps({"ok": False, "report": [f"Cannot reopen {device}: {exc}"]}))
        return 0
    try:
        for off in read_order:
            start = time.perf_counter()
            try:
                os.lseek(fd, off, os.SEEK_SET)
                buf = os.read(fd, BLOCK)
            except OSError as exc:
                errors.append(f"read at {off}: {exc.strerror}")
                continue
            read_ms.append((time.perf_counter() - start) * 1000)
            if buf != make_block(off):
                mismatches += 1
    finally:
        os.close(fd)

    report = []
    ok = not errors and mismatches == 0

    if write_ms:
        w_med, w_p99 = statistics.median(write_ms), percentile(write_ms, 99)
        report.append(
            f"random write 4KiB x{len(write_ms)}: median {w_med:.2f} ms, "
            f"p99 {w_p99:.2f} ms, max {max(write_ms):.2f} ms "
            f"({(BLOCK / 1024) / (w_med if w_med else 1):.1f} MB/s at the median)"
        )
        # A long tail is the signal worth surfacing. The threshold is a heuristic, so it is
        # reported as an observation rather than folded into the pass/fail verdict.
        if w_p99 > w_med * 10 and w_p99 > 50:
            report.append(
                f"  NOTE: p99 write latency is {w_p99 / w_med:.0f}x the median — a long tail like "
                f"this often means the controller is struggling to find clean erase blocks."
            )
    if read_ms:
        r_med = statistics.median(read_ms)
        report.append(
            f"random read  4KiB x{len(read_ms)}: median {r_med:.2f} ms, "
            f"p99 {percentile(read_ms, 99):.2f} ms, max {max(read_ms):.2f} ms"
        )

    if mismatches:
        report.append(f"DATA MISMATCH at {mismatches} of {len(read_order)} random offsets.")
    if errors:
        report.extend(errors[:10])
        if len(errors) > 10:
            report.append(f"... and {len(errors) - 10} more I/O errors")

    report.append(
        "VERDICT: PASSED — every randomly-addressed block returned its own data."
        if ok
        else "VERDICT: FAILED — the device did not return what was written at some random offsets."
    )

    print(json.dumps({"ok": ok, "mismatches": mismatches, "errors": len(errors), "report": report}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
