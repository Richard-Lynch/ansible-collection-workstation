#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Survey a Raspberry Pi's boot state. READ-ONLY — writes nothing, changes nothing.

Emits one JSON object so a play can assert on fields rather than grep stdout.

WHY A SCRIPT RATHER THAN A PILE OF command: TASKS. Every fact here needs either a small parse
(BOOT_ORDER nibbles, get_throttled bitfields) or a join across two sources (which by-id name
corresponds to the device backing /). Doing that in Jinja produces expressions nobody can review,
and this repo has a documented history of exactly that going silently wrong.

WHAT IT DELIBERATELY DOES NOT DO: decide anything. It reports; the play asserts. A probe that
returns "ok: true" has already made the judgement call the play exists to make.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# BOOT_ORDER nibble meanings, per the Raspberry Pi bootloader documentation. Read RIGHT TO LEFT:
# the least-significant nibble is tried first.
BOOT_MODES = {
    "0": "SD CARD DETECT (retry until a card is inserted)",
    "1": "SD card",
    "2": "network (TFTP)",
    "3": "RPIBOOT",
    "4": "USB mass storage",
    "5": "BCM-USB-MSD",
    "6": "NVMe (CM4/Pi5)",
    "7": "HTTP",
    "e": "STOP (halt with an error pattern)",
    "f": "RESTART the sequence",
}

# `vcgencmd get_throttled` bitfield. Bits 0-3 are the CURRENT state; bits 16-19 are STICKY
# "has happened since boot". The sticky bits are the ones worth alerting on — an undervoltage
# event that has already passed still explains a corrupted write ten minutes later.
THROTTLE_BITS = {
    0: "under-voltage NOW",
    1: "arm frequency capped NOW",
    2: "currently throttled",
    3: "soft temperature limit active",
    16: "under-voltage HAS OCCURRED since boot",
    17: "arm frequency capping HAS OCCURRED since boot",
    18: "throttling HAS OCCURRED since boot",
    19: "soft temperature limit HAS OCCURRED since boot",
}


def run(cmd: list[str]) -> tuple[int, str]:
    """Run a command, returning (rc, stdout). Never raises — an absent tool is a fact to report."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def decode_boot_order(value: str) -> list[str]:
    """Decode BOOT_ORDER into the order the firmware actually tries, first attempt first.

    Nibbles are read right to left, so the string is reversed before mapping. Getting this
    backwards is the whole point of reporting it in words: 0xf14 and 0xf41 look almost identical
    and mean opposite things.
    """
    digits = value.lower().removeprefix("0x")
    if not digits:
        return []
    return [f"{d}={BOOT_MODES.get(d, 'unknown')}" for d in reversed(digits)]


def decode_throttled(hex_value: str) -> list[str]:
    try:
        bits = int(hex_value, 16)
    except ValueError:
        return []
    return [text for bit, text in sorted(THROTTLE_BITS.items()) if bits & (1 << bit)]


def by_id_map() -> dict[str, str]:
    """Map kernel name (sda, mmcblk0) -> its /dev/disk/by-id name.

    by-id is what inventory declares, because kernel names renumber between boots and between USB
    enumeration orders. Where several by-id links point at one device the shortest is chosen, which
    prefers `usb-Samsung_SSD_1234-0:0` over its `-part1` children.
    """
    out: dict[str, str] = {}
    for link in sorted(glob.glob("/dev/disk/by-id/*")):
        try:
            target = os.path.basename(os.path.realpath(link))
        except OSError:
            continue
        name = os.path.basename(link)
        if target not in out or len(name) < len(out[target]):
            out[target] = name
    return out


def root_source() -> dict:
    """Which device backs `/`, resolved to a stable by-id name where possible."""
    rc, src = run(["findmnt", "-n", "-o", "SOURCE", "--target", "/"])
    src = src.split("[")[0]  # btrfs/overlay subvolume suffix, if any
    info: dict = {"raw": src or None, "by_id": None, "kernel": None, "medium": "unknown"}
    if rc != 0 or not src:
        return info

    real = os.path.realpath(src) if src.startswith("/dev/") else src
    kernel = os.path.basename(real)
    info["kernel"] = kernel
    # Strip the partition suffix to get the whole disk: sda2 -> sda, mmcblk0p2 -> mmcblk0.
    whole = re.sub(r"p?\d+$", "", kernel)
    info["by_id"] = by_id_map().get(whole) or by_id_map().get(kernel)
    if whole.startswith("mmcblk"):
        info["medium"] = "sd-card"
    elif whole.startswith(("sd", "nvme")):
        info["medium"] = "usb-or-nvme"
    return info


def block_devices() -> list[dict]:
    rc, out = run(["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,TRAN,MODEL,MOUNTPOINT"])
    if rc != 0 or not out:
        return []
    try:
        tree = json.loads(out)
    except json.JSONDecodeError:
        return []
    ids = by_id_map()
    devices = []
    for d in tree.get("blockdevices", []):
        if d.get("type") != "disk":
            continue
        devices.append(
            {
                "kernel": d.get("name"),
                "by_id": ids.get(d.get("name")),
                "size_gb": round((d.get("size") or 0) / 1e9, 1),
                "transport": d.get("tran"),
                "model": (d.get("model") or "").strip() or None,
            }
        )
    return devices


def usb_bridges() -> list[dict]:
    """USB storage bridges and whether UAS is bound.

    Reported because a bridge that mishandles UAS corrupts data under load, and the SSD is the
    single point of failure in a USB-boot design. The fix is a usb-storage.quirks=VID:PID:u entry
    declared in inventory — so the VID:PID has to be discoverable without guesswork.
    """
    rc, out = run(["lsusb"])
    bridges = []
    if rc == 0:
        for line in out.splitlines():
            m = re.search(r"ID ([0-9a-f]{4}):([0-9a-f]{4})\s*(.*)", line, re.I)
            if not m:
                continue
            vid, pid, desc = m.group(1), m.group(2), m.group(3).strip()
            if re.search(r"stor|sata|disk|ssd|nvme|asmedia|jmicron|realtek", desc, re.I):
                bridges.append({"vid_pid": f"{vid}:{pid}", "description": desc})
    uas = Path("/sys/module/uas").exists()
    for b in bridges:
        b["uas_module_loaded"] = uas
    return bridges


def cmdline_flags() -> dict:
    """Flags from /proc/cmdline — the EFFECTIVE kernel command line.

    /proc/cmdline, NOT /boot/firmware/cmdline.txt, and the distinction is load-bearing: the Pi
    firmware INJECTS arguments that never appear in that file. Most importantly it injects
    cgroup_disable=memory, so a host can have cgroup_enable=memory sitting in cmdline.txt and
    still have the memory controller disabled. Reading the config file to verify would be a check
    that cannot fail.
    """
    try:
        raw = Path("/proc/cmdline").read_text().strip()
    except OSError:
        return {}
    tokens = raw.split()
    controllers = ""
    try:
        controllers = Path("/sys/fs/cgroup/cgroup.controllers").read_text().strip()
    except OSError:
        pass
    return {
        "raw": raw,
        "root": next((t.removeprefix("root=") for t in tokens if t.startswith("root=")), None),
        "panic": next((t.removeprefix("panic=") for t in tokens if t.startswith("panic=")), None),
        "usb_storage_quirks": next(
            (
                t.removeprefix("usb-storage.quirks=")
                for t in tokens
                if t.startswith("usb-storage.quirks=")
            ),
            None,
        ),
        # `overlayroot=tmpfs`, NOT `boot=overlay`. Bookworm's raspi-config uses the overlayroot
        # package; `boot=overlay` is the bullseye-era initramfs mechanism and never appears on
        # this OS, so testing for it reported a standing falsehood. Verified against the
        # raspi-config bookworm branch source.
        "boot_overlay": "overlayroot=tmpfs" in tokens,
        # The effective truth about the memory cgroup, from the kernel rather than from config.
        "cgroup_memory_available": "memory" in controllers.split(),
        "cgroup_disable_present": any(t.startswith("cgroup_disable=") for t in tokens),
    }


def eeprom() -> dict:
    """Bootloader EEPROM config and version.

    NOTE `rpi-eeprom-config` with no arguments reports the bootloader that booted THIS session —
    so immediately after staging an update it still shows the OLD values. That is why the play
    asserts a staged file after a change and the live value only after a reboot.
    """
    rc, cfg = run(["rpi-eeprom-config"])
    info: dict = {
        "available": rc == 0,
        "config": cfg or None,
        "boot_order": None,
        "boot_order_decoded": [],
        "disable_hdmi": None,
        "version": None,
    }
    if rc == 0 and cfg:
        m = re.search(r"^BOOT_ORDER=(\S+)", cfg, re.M)
        if m:
            info["boot_order"] = m.group(1)
            info["boot_order_decoded"] = decode_boot_order(m.group(1))
        # DISABLE_HDMI=1 has been reported to make BOOT_ORDER be ignored entirely
        # (raspberrypi/rpi-eeprom#466) — a Pi whose fallback design is inert while appearing
        # configured. Reported so the play can refuse rather than silently trust BOOT_ORDER.
        h = re.search(r"^DISABLE_HDMI=(\S+)", cfg, re.M)
        info["disable_hdmi"] = h.group(1) if h else None

    # PARSING THE VERSION. Verified against raspberrypi/rpi-eeprom master:
    #
    #   echo "   CURRENT: $(date -u "-d@${BOOTLOADER_CURRENT_VERSION}") (${VERSION})"
    #
    # i.e. a human date plus a UNIX EPOCH in parentheses — there is NO ISO date anywhere in the
    # output. An earlier version of this probe searched for `\d{4}-\d{2}-\d{2}`, matched nothing,
    # and returned version=None on every board; the caller's "bootloader must be new enough" gate
    # then refused EVERY healthy Pi with a misleading "too old", and the report crashed comparing
    # None to a string.
    #
    # Only the BOOTLOADER's CURRENT line carries parentheses (the Pi 4 VL805 line is bare), so the
    # epoch capture cannot pick up the wrong one.
    #
    # And rc: `rpi-eeprom-update` in info mode exits EXIT_UPDATE_REQUIRED=1 when an update is
    # available, so demanding rc==0 skipped parsing on exactly the boards that most need
    # attention. 0 and 1 are both informative; 2 (failed) and 3 (frozen) are not.
    rc2, upd = run(["rpi-eeprom-update"])
    if rc2 in (0, 1) and upd:
        m = re.search(r"^\s*CURRENT:.*\((\d+)\)", upd, re.M)
        if m:
            epoch = int(m.group(1))
            info["version_epoch"] = epoch
            # Derived ISO date, so callers can compare lexicographically against a declared
            # minimum like "2020-09-03" — which is how the min-version gate reads.
            info["version"] = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d")
        info["update_available"] = rc2 == 1
        info["update_raw"] = upd
    return info


def overlay_state() -> dict:
    """Is the running root actually read-only, and is the overlay configured?

    BOTH are reported, because they answer different questions and are true at different times:
    `boot=overlay` in the config takes effect at the NEXT boot, so config-says-yes plus
    live-says-writable is the expected state between hardening and rebooting — not a fault.
    """
    rc, opts = run(["findmnt", "-n", "-o", "OPTIONS", "--target", "/"])
    rc2, fstype = run(["findmnt", "-n", "-o", "FSTYPE", "--target", "/"])
    return {
        "live_read_only": rc == 0 and opts.split(",")[0] == "ro",
        "live_fstype": fstype or None,
        "live_is_overlay": fstype == "overlay",
        "options": opts or None,
    }


def main() -> int:
    rc_model, model = run(["cat", "/proc/device-tree/model"])
    serial = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("serial"):
                serial = line.split(":", 1)[1].strip()
    except OSError:
        pass

    rc_t, throttled = run(["vcgencmd", "get_throttled"])
    throttle_hex = throttled.split("=")[-1] if "=" in throttled else ""
    rc_temp, temp = run(["vcgencmd", "measure_temp"])

    report = {
        "model": model.replace("\x00", "").strip() or None,
        "soc_serial": serial,
        "root": root_source(),
        "block_devices": block_devices(),
        "usb_bridges": usb_bridges(),
        "cmdline": cmdline_flags(),
        "eeprom": eeprom(),
        "overlay": overlay_state(),
        "throttling": {
            "raw": throttle_hex or None,
            "flags": decode_throttled(throttle_hex) if throttle_hex else [],
        },
        "temperature": temp.replace("temp=", "") if rc_temp == 0 else None,
        "watchdog": {
            "device_present": Path("/dev/watchdog").exists(),
            "runtime_usec": run(["systemctl", "show", "-p", "RuntimeWatchdogUSec", "--value"])[1]
            or None,
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
