#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Data-retention test for USB storage: write now, verify later.

Called from the usb_media role's retention entrypoint.
Two phases, invoked as separate runs:

    usb_retention.py write  <device> <total_size> <samples> <statefile>
    usb_retention.py verify <device> <statefile>

WHY THIS EXISTS AND WHAT IT ADDS. Every other check here writes and reads back immediately, so it
can only see faults that are present at that instant. Worn or counterfeit flash has a distinct
failure mode that such a test cannot detect at all: cells that ACCEPT a write, return it correctly
seconds later, and then lose their charge over minutes to hours. The stick passes every immediate
test and still hands back corrupted data the next day.

That matters for install media more than it first appears. A stick written on Monday and booted on
Friday has had four days for weak cells to decay, and the symptom — an installer that dies partway
with a checksum error, or a machine that boots once and not again — looks like a bad image or bad
firmware rather than bad flash.

HOW THE DELAY IS HANDLED. The wait is not this script's job. It writes a pattern, records what it
wrote to a state file, and exits; a separate verify run compares the device against that record
whenever the caller comes back. This means the delay can be minutes (a play that sleeps) or days
(a run now, a run on Friday) with no process held open in between, and no assumption that anything
stayed in memory.

WHAT IT CANNOT PROVE. A pass means the sampled blocks survived THAT interval. Retention faults are
time-and-temperature dependent, so a stick that holds data for an hour may still not hold it for a
month; a longer wait is a stronger result. The report always states the measured interval so the
claim is bounded by what was actually observed.

Always exits 0 with JSON on stdout.
"""

import hashlib
import json
import os
import sys
import time

BLOCK = 1024 * 1024
MAGIC = b"IAAC-RETENTION-V1"


def make_block(offset: int, nonce: str) -> bytes:
    """Content bound to BOTH the offset and this run's nonce.

    The nonce matters: without it a verify run could be satisfied by a pattern left behind by an
    EARLIER retention test, reporting success for data this run never wrote. It is generated once
    at write time and stored in the state file.
    """
    head = b"%s nonce=%s off=%020d " % (MAGIC, nonce.encode(), offset)
    digest = hashlib.sha256(head).digest()
    body = (digest * (BLOCK // len(digest) + 1))[: BLOCK - len(head)]
    return head + body


def probe_offsets(total_size: int, samples: int):
    last = ((total_size - BLOCK) // BLOCK) * BLOCK
    offs = {
        ((total_size - BLOCK) * i // max(samples - 1, 1) // BLOCK) * BLOCK for i in range(samples)
    }
    offs.add(0)
    offs.add(last)
    return sorted(o for o in offs if 0 <= o <= last)


def phase_write(device, total_size, samples, statefile) -> int:
    # Nonce identifying THIS run. Second-resolution time alone is not enough: two runs started
    # within the same second produce identical nonces and therefore identical block content, so a
    # later verify cannot tell "my pattern survived" from "another run overwrote it with the same
    # bytes" — it reports a false PASS. os.urandom makes collisions irrelevant; the timestamp is kept as a readable
    # prefix so a hex dump still says roughly when a block was written.
    nonce = f"{int(time.time()):x}-{os.urandom(4).hex()}"
    offsets = probe_offsets(total_size, samples)
    written, errors = [], []

    fd = os.open(device, os.O_WRONLY)
    try:
        for off in offsets:
            try:
                os.lseek(fd, off, os.SEEK_SET)
                os.write(fd, make_block(off, nonce))
                written.append(off)
            except OSError as exc:
                errors.append(f"offset {off}: write failed ({exc.strerror})")
        try:
            os.fsync(fd)
        except OSError:
            pass
    finally:
        os.close(fd)

    # STATE FILE HANDLING IS SECURITY-SENSITIVE, because this phase runs as root under `become`.
    #
    # A plain open(path, "w") in a world-writable directory such as /tmp is an arbitrary-file
    # overwrite primitive: any local user can pre-create the path as a symlink to something they
    # could not otherwise touch, and root's write follows it. The verify phase then compounds it
    # by trusting JSON that anyone could have replaced — and those values drive the offsets it
    # reads. So: a root-owned parent directory (0700), an exclusive no-follow create, and 0600 on
    # the file itself.
    statefile = os.path.expanduser(statefile)
    parent = os.path.dirname(statefile) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)
    # exist_ok=True does not tighten an existing directory's mode, so set it explicitly.
    os.chmod(parent, 0o700)

    state = {
        "device": device,
        "nonce": nonce,
        "written_at": time.time(),
        "offsets": written,
        "total_size": total_size,
    }
    # O_EXCL|O_NOFOLLOW: refuse to write through a symlink, and refuse to reuse a file someone
    # else planted. A stale state file from an earlier run is removed first — deliberately with
    # unlink rather than by opening it, so the removal cannot follow a link either.
    try:
        os.unlink(statefile)
    except FileNotFoundError:
        pass
    fd = os.open(statefile, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(state, handle)

    report = [
        f"retention: wrote {len(written)} x {BLOCK // 1024}KiB stamped blocks "
        f"(nonce {nonce}) across {total_size / 1e9:.1f} GB",
        f"state saved to {statefile}; run the verify phase after a delay.",
    ]
    report.extend(errors[:10])
    print(json.dumps({"ok": not errors, "phase": "write", "nonce": nonce, "report": report}))
    return 0


def phase_verify(device, statefile) -> int:
    # Read with the same care the write used: this file's contents drive the offsets read back
    # from the device, so a file an unprivileged user could have swapped is not safe to trust.
    # O_NOFOLLOW refuses a symlink; the fstat then refuses anything not owned by this user (root
    # under become) or writable by anyone else.
    statefile = os.path.expanduser(statefile)
    try:
        fd = os.open(statefile, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "phase": "verify",
                    "report": [f"Cannot open state file {statefile}: {exc}"],
                }
            )
        )
        return 0
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or (info.st_mode & 0o077):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "phase": "verify",
                        "report": [
                            f"REFUSING to trust {statefile}: owned by uid {info.st_uid} "
                            f"(expected {os.geteuid()}) or writable by others (mode "
                            f"{info.st_mode & 0o777:04o}). Its contents drive raw-device reads, so a file "
                            f"another user could have replaced is not safe to act on."
                        ],
                    }
                )
            )
            return 0
        with os.fdopen(fd, "r") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "phase": "verify",
                    "report": [f"Cannot read state file {statefile}: {exc}"],
                }
            )
        )
        return 0

    elapsed = time.time() - state["written_at"]
    nonce = state["nonce"]
    failures = []

    # Guard against verifying a DIFFERENT device than was written. Device ids are not stable
    # across replugs, so a state file naming /dev/rdisk4 says nothing about which stick that is
    # now — but a mismatch in the recorded path is still worth refusing on, and the nonce check
    # below is what actually proves the data came from this run.
    if state.get("device") != device:
        failures.append(f"state file was written for {state.get('device')}, not {device}")

    fd = os.open(device, os.O_RDONLY)
    try:
        for off in state["offsets"]:
            try:
                os.lseek(fd, off, os.SEEK_SET)
                buf = os.read(fd, BLOCK)
            except OSError as exc:
                failures.append(f"offset {off}: read failed ({exc.strerror})")
                continue
            if buf != make_block(off, nonce):
                # THREE OUTCOMES, and telling them apart is what makes the verdict trustworthy:
                #   - our magic AND our nonce, wrong bytes  -> genuine DECAY (the finding)
                #   - our magic but a DIFFERENT nonce       -> another run of this test wrote here
                #   - no magic at all                       -> something else entirely wrote here
                # The middle case is the one that matters most in practice: it is a spoiled
                # measurement, not a failing stick, and must never be reported as decay. Checking
                # only the magic conflated it with real decay — every retention run shares the
                # same magic, so a second run's blocks looked "ours but corrupted".
                nonce_marker = b"nonce=" + nonce.encode()
                if buf.startswith(MAGIC) and nonce_marker not in buf[:128]:
                    failures.append(
                        f"offset {off}: block carries a DIFFERENT run's nonce — something "
                        f"overwrote it between the phases"
                    )
                elif buf.startswith(MAGIC):
                    failures.append(
                        f"offset {off}: block DECAYED — our stamp is present but the contents "
                        f"changed since it was written"
                    )
                else:
                    failures.append(
                        f"offset {off}: block no longer contains this run's data at all"
                    )
    finally:
        os.close(fd)

    # DISTINGUISH INTERFERENCE FROM DECAY. A block that no longer carries OUR nonce was
    # overwritten by something else — most often another run of this very test against the same
    # device while the first was still waiting, which is an easy mistake to make because the wait
    # looks like idle time when it is actually the measurement. That is a spoiled test, not a
    # failing stick, and reporting it as "this stick loses data" would condemn good hardware.
    #
    # Decay and interference are already distinguished above by whether the magic survived; this
    # summarises the distinction in the verdict so the reader is not left to infer it.
    overwritten = sum(
        1 for f in failures if "no longer contains" in f or "DIFFERENT run's nonce" in f
    )
    decayed = sum(1 for f in failures if "DECAYED" in f)

    hours = elapsed / 3600
    interval = f"{elapsed:.0f} seconds" if elapsed < 300 else f"{hours:.1f} hours"
    report = [
        f"retention: re-read {len(state['offsets'])} blocks after {interval} " f"(nonce {nonce})"
    ]
    if failures:
        report.extend(failures[:20])
        if len(failures) > 20:
            report.append(f"... and {len(failures) - 20} more")
        if overwritten and not decayed:
            report.append(
                f"VERDICT: INCONCLUSIVE — {overwritten} block(s) carry a DIFFERENT nonce, i.e. "
                f"something else wrote to this device between the two phases (another run of "
                f"this test against the same device is the usual cause). This is a spoiled "
                f"measurement, not evidence about the hardware. Re-run, and leave the device "
                f"untouched during the wait."
            )
        else:
            report.append(
                f"VERDICT: FAILED — data did not survive the interval "
                f"({decayed} decayed, {overwritten} overwritten). Do not trust this stick."
            )
    else:
        report.append(
            f"VERDICT: PASSED — every block survived {interval} unchanged. Note this bounds the "
            f"claim to that interval; retention faults are time- and temperature-dependent, so a "
            f"longer wait is a stronger result."
        )

    # `ok` stays False for an inconclusive run — it did not prove anything — but `inconclusive`
    # lets the play distinguish "spoiled test" from "condemn this stick" in its failure message.
    print(
        json.dumps(
            {
                "ok": not failures,
                "phase": "verify",
                "inconclusive": bool(overwritten and not decayed),
                "decayed": decayed,
                "overwritten": overwritten,
                "elapsed_seconds": round(elapsed),
                "report": report,
            }
        )
    )
    return 0


def main() -> int:
    phase = sys.argv[1]
    if phase == "write":
        return phase_write(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
    if phase == "verify":
        return phase_verify(sys.argv[2], sys.argv[3])
    print(json.dumps({"ok": False, "report": [f"Unknown phase '{phase}'"]}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
