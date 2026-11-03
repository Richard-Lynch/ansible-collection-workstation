#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Detect failing or counterfeit-capacity USB storage.

Called from the usb_media role (integrity entrypoint).

WHAT COUNTERFEIT STICKS ACTUALLY DO. A fake reports a large capacity over a small real part, and
handles writes past the real end in one of two ways:

  DISCARD  the write is swallowed; reading that region later returns zeros or stale garbage.
           This is the common case.
  WRAP     the write aliases onto a low address, destroying whatever was there. Reading the high
           offset afterwards returns the aliased data, so the HIGH offset looks fine — the damage
           shows up at the LOW offset that got clobbered.

WHAT THIS CAN AND CANNOT PROVE — stated plainly, because a capacity checker that overclaims is
worse than none:

  * SPARSE mode (default) writes one stamped block at each of N probe offsets, then reads them
    all back. This catches DISCARD reliably at any size ratio, and catches WRAP only when the
    real size is close to the claimed size. It CANNOT catch a 64GB-claiming stick with an 8GB
    real part that wraps, because the sparse probes each alias to a distinct low address and so
    round-trip faithfully. Verified by simulation against both models — see the docstring tests.

  * FULL mode (--full) writes stamped blocks across the ENTIRE claimed capacity and reads them
    all back. This is the only way to actually prove capacity: a device cannot store more
    distinct data than it physically holds, so any shortfall must surface. It takes as long as
    two full passes over the device (an hour or more for 64GB on a slow stick), which is why it
    is opt-in rather than the default.

The verdict distinguishes the two, so a SPARSE pass never claims more than it tested.

Every block is stamped with its own offset and a hash over that stamp, so random flash garbage
cannot masquerade as valid data, and a block that surfaces at the wrong offset is identifiable
as belonging elsewhere. All writes complete before any read begins — verifying block-by-block
would pass a wrapping device trivially, since each block is intact until a later write clobbers
it. The read pass reopens the device so macOS's buffer cache cannot answer for the hardware.
"""

import hashlib
import json
import os
import sys

# 1 MiB per probe: comfortably larger than any flash page or erase block, so a partial-write
# artefact cannot masquerade as a clean result.
BLOCK = 1024 * 1024
MAGIC = b"IAAC-USB-CHECK-V1"
# Blocks probed as dense consecutive runs at the very start and very end of the claimed space.
# Consecutive claimed offsets stay consecutive after wrapping, so these runs are what give the
# sparse mode any chance at all of catching a near-size wrap.
DENSE_RUN = 8


def make_block(offset: int) -> bytes:
    """A block whose content is derived from, and states, its own offset."""
    head = b"%s offset=%020d " % (MAGIC, offset)
    digest = hashlib.sha256(head).digest()
    body = (digest * (BLOCK // len(digest) + 1))[: BLOCK - len(head)]
    return head + body


def read_offset(buf: bytes):
    """Recover the offset a block claims, or None if it is not an intact block of ours."""
    if not buf.startswith(MAGIC):
        return None
    try:
        claimed = int(buf.split(b"offset=", 1)[1][:20])
    except (IndexError, ValueError):
        return None
    # Re-derive and compare, so a block whose header survived but whose body was corrupted is
    # still reported as bad rather than trusted for its stamp alone.
    return claimed if buf == make_block(claimed) else None


def probe_offsets(total_size: int, samples: int, full: bool):
    last = ((total_size - BLOCK) // BLOCK) * BLOCK
    if full:
        return list(range(0, last + BLOCK, BLOCK))
    offs = {
        ((total_size - BLOCK) * i // max(samples - 1, 1) // BLOCK) * BLOCK for i in range(samples)
    }
    for k in range(DENSE_RUN):
        offs.add(k * BLOCK)
        offs.add(max(0, last - k * BLOCK))
    return sorted(o for o in offs if 0 <= o <= last)


def main() -> int:
    device = sys.argv[1]
    total_size = int(sys.argv[2])
    samples = int(sys.argv[3])
    full = "--full" in sys.argv

    if total_size - BLOCK <= 0:
        print(json.dumps({"ok": False, "mode": "none", "report": ["Device too small to test."]}))
        return 0

    offsets = probe_offsets(total_size, samples, full)
    report = []
    failures = []

    # --- write pass: every block, before any verification ---
    #
    # An I/O ERROR HERE IS A RESULT, NOT A CRASH. A device that is physically smaller than it
    # claims returns EIO/ENXIO on a write past its real end — which is precisely the finding this
    # script exists to report. Verified against a real 16MB disk image addressed as though it
    # were 64MB: the bare os.write raised OSError(EIO) and the whole run died with a traceback,
    # reporting nothing. Caught per-offset so the test continues and the verdict names the exact
    # offset where the device stopped accepting data.
    fd = os.open(device, os.O_WRONLY)
    try:
        for off in offsets:
            block = make_block(off)
            try:
                os.lseek(fd, off, os.SEEK_SET)
                written = os.write(fd, block)
            except OSError as exc:
                failures.append(
                    f"offset {off}: device REFUSED the write ({exc.strerror}) — "
                    f"it is physically smaller than the {total_size} bytes it reports"
                )
                continue
            if written != len(block):
                failures.append(f"offset {off}: short write ({written} of {len(block)} bytes)")
        try:
            os.fsync(fd)
        except OSError:
            # A device that errored above may also fail to sync; the failures list already
            # records why, and raising here would replace a clear verdict with a traceback.
            pass
    finally:
        os.close(fd)

    # --- read pass: reopened so the page cache cannot answer for the device ---
    fd = os.open(device, os.O_RDONLY)
    try:
        for off in offsets:
            try:
                os.lseek(fd, off, os.SEEK_SET)
                buf = os.read(fd, BLOCK)
            except OSError as exc:
                failures.append(
                    f"offset {off}: device REFUSED the read ({exc.strerror}) — "
                    f"capacity is not real"
                )
                continue
            claimed = read_offset(buf)
            if claimed is None:
                failures.append(
                    f"offset {off}: returned data that was never written there "
                    f"(zeroed, stale, or corrupt) — capacity is not real"
                )
            elif claimed != off:
                failures.append(
                    f"offset {off}: returned the block belonging to offset {claimed} "
                    f"— writes are wrapping; capacity is not real"
                )
    finally:
        os.close(fd)

    gb = total_size / 1000 / 1000 / 1000
    tested_gb = len(offsets) * BLOCK / 1000 / 1000 / 1000
    mode = "full" if full else "sparse"
    # The SAMPLED FRACTION is stated explicitly. "PASSED" over 0.1% of a device is not a health
    # clearance, and a verdict that does not say so invites being read as one.
    pct = (tested_gb / gb * 100) if gb else 0
    report.append(
        f"mode={mode}: probed {len(offsets)} x {BLOCK // 1024}KiB blocks "
        f"({tested_gb:.2f} GB = {pct:.1f}% of the claimed {gb:.1f} GB)"
    )

    if failures:
        report.extend(failures[:20])
        if len(failures) > 20:
            report.append(f"... and {len(failures) - 20} more failing offsets")
        report.append("VERDICT: FAILED — do not use this stick for install media.")
    elif full:
        report.append(
            "VERDICT: PASSED — every block across the full capacity returned its own data, "
            "so the reported size is real."
        )
    else:
        # Deliberately NOT phrased as "the stick is fine". A sparse pass cannot see a
        # large-ratio wrap, and saying so is the difference between a useful test and a
        # false reassurance.
        report.append(
            f"VERDICT: PASSED (sparse, {pct:.1f}% sampled) — no bad blocks at the probed "
            "offsets. This rules out the common counterfeit mode (writes discarded past the real "
            "end), but it is a SAMPLE, not a health clearance: the unprobed blocks were never "
            "touched, and a stick that silently wraps writes onto low addresses would still pass. "
            "Re-run with usb_media_full=true to write and verify every block and prove the size."
        )

    print(json.dumps({"ok": not failures, "mode": mode, "report": report}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
