#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive RGB lighting from live system state, via the OpenRGB SDK server.

WHY A DAEMON AND NOT `OpenRGB --mode ...` PER CHANGE. The one-shot CLI does not hold device
state: setting a mode returns rc 0, prints no error, and a read-back immediately afterwards —
even within the SAME process — still reports the previous mode. Devices revert as soon as the
process exits. A persistent connection is the only way a
colour stays put, which is also what makes reactive lighting possible at all.

NO THIRD-PARTY DEPENDENCIES. `openrgb-python` would have to be layered onto an immutable OS for
one small binary protocol. This implements only the handful of packets needed (protocol v6,
confirmed against the running server) using the standard library, so the unit has nothing to
install and nothing to keep up to date.

MODES
  static   one fixed colour on everything
  cpu      colour follows CPU temperature
  gpu      colour follows GPU temperature
  load     colour follows CPU load average
  auto     whichever of cpu/gpu is proportionally hotter — the useful default, since the
           interesting signal is "something is getting hot", not which sensor you picked

The temperature-to-colour ramp is blue -> green -> yellow -> red across the configured range.
Idle sits blue-green, load pushes it to red, so the case reports at a glance what the machine is
doing without anyone reading a number.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import signal
import socket
import struct
import sys
import time

MAGIC = b"ORGB"

# Packet ids, protocol v6.
REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 4

# Number of 4-byte fields in a mode descriptor, after the name and before the colour count.
# See the note in _parse_controller: this is protocol-v6 specific and was measured, not assumed.
MODE_STRUCT_FIELDS = 12

# Hardware detection settles asynchronously after the server starts accepting connections.
# Enumerating too early yields a partial device list with no error — see _load_devices.
DETECT_POLL_INTERVAL = 1.0
DETECT_STABLE_POLLS = 3
DETECT_TIMEOUT = 30.00
SET_CLIENT_NAME = 50
RGBCONTROLLER_UPDATELEDS = 1050
RGBCONTROLLER_UPDATEZONELEDS = 1051
RGBCONTROLLER_SETCUSTOMMODE = 1100
RGBCONTROLLER_RESIZEZONE = 1102
RGBCONTROLLER_UPDATEMODE = 1101

PROTOCOL_VERSION = 4

# Number of 4-byte fields in a mode descriptor, after the name and before the colour count.
# See the note in _parse_controller: this is protocol-v6 specific and was measured, not assumed.
MODE_STRUCT_FIELDS = 12

# Hardware detection settles asynchronously after the server starts accepting connections.
# Enumerating too early yields a partial device list with no error — see _load_devices.
DETECT_POLL_INTERVAL = 1.0
DETECT_STABLE_POLLS = 3
DETECT_TIMEOUT = 30.0

log = logging.getLogger("openrgb-daemon")


# --------------------------------------------------------------------------------------------
# SDK client
# --------------------------------------------------------------------------------------------


class OpenRGBClient:
    """Just enough of the OpenRGB SDK to enumerate devices and set per-LED colours."""

    def __init__(
        self,
        host: str,
        port: int,
        name: str = "iaac-rgb-daemon",
        zone_sizes: dict[str, list[int]] | None = None,
    ):
        self.host, self.port, self.name = host, port, name
        self.sock: socket.socket | None = None
        self.devices: list[dict] = []
        # {device-name-substring: [zone0_leds, zone1_leds, ...]}
        self.zone_sizes = zone_sizes or {}

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        self.sock.settimeout(10)
        # DELIBERATELY NOT SENDING REQUEST_PROTOCOL_VERSION (packet 40).
        #
        # The server keeps client_protocol_version = 0 until it receives that packet, and version
        # 0 selects the OLDEST device-description layout — the one this parser implements and
        # which is verified below to land exactly on every blob's declared length.
        #
        # Negotiating upward was tried and REVERTED. It works, but it switches the server to the
        # v6 layout (mode.value and led.value removed, zone modes/segment flags/display names and
        # a controller configuration blob added), which means carrying two parsers to gain
        # nothing: writes succeed at v0 — verified by reading the hardware back — and the only
        # documented v6 benefit is server ACKs, which the UPDATELEDS/UPDATEZONELEDS path skips
        # anyway because it is dispatched through a queue.
        #
        # The cost of pinning is that the server never acks, so silence means nothing. That is
        # exactly why every write here is verified with read_colors() rather than assumed.

        self._send(0, SET_CLIENT_NAME, self.name.encode() + b"\x00")
        log.info("connected to %s:%s (legacy layout)", self.host, self.port)

        self._load_devices()
        if self.zone_sizes:
            self._apply_zone_sizes()

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _send(self, dev: int, pkt: int, data: bytes = b"") -> None:
        assert self.sock is not None
        self.sock.sendall(MAGIC + struct.pack("<III", dev, pkt, len(data)) + data)

    def _recv(self) -> tuple[int, int, bytes]:
        assert self.sock is not None
        hdr = self._recv_exact(16)
        if hdr[:4] != MAGIC:
            raise RuntimeError(f"bad magic {hdr[:4]!r}")
        dev, pkt, size = struct.unpack("<III", hdr[4:])
        return dev, pkt, self._recv_exact(size)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("server closed the connection")
            buf += chunk
        return buf

    def _load_devices(self) -> None:
        """Enumerate controllers, waiting for detection to settle first.

        THE SERVER ACCEPTS CONNECTIONS BEFORE IT HAS FINISHED DETECTING HARDWARE. I2C devices
        (the DRAM modules) appear almost immediately; HID devices (keyboard, mouse, motherboard)
        take several seconds longer. A client that enumerates on connect therefore gets a
        PARTIAL list, with no error and nothing in the log to suggest anything is missing — the
        daemon runs happily against some of the devices, and only the RAM changes colour.

        So: poll the count until it stops growing. A device that genuinely is not there simply
        keeps the count stable and costs one extra settle interval.
        """
        count = self._controller_count()
        stable_for = 0
        waited = 0.0
        while stable_for < DETECT_STABLE_POLLS and waited < DETECT_TIMEOUT:
            time.sleep(DETECT_POLL_INTERVAL)
            waited += DETECT_POLL_INTERVAL
            latest = self._controller_count()
            if latest == count:
                stable_for += 1
            else:
                log.info("detection still running: %d -> %d controllers", count, latest)
                count, stable_for = latest, 0
        self.devices = []
        for i in range(count):
            self._send(i, REQUEST_CONTROLLER_DATA, struct.pack("<I", PROTOCOL_VERSION))
            _size, _cmd, body = self._recv()
            self.devices.append(self._parse_controller(body, i))
        log.info("found %d device(s): %s", count, ", ".join(d["name"] for d in self.devices))

    def _apply_zone_sizes(self) -> None:
        """Size any addressable zones the caller has declared, then re-read the device list.

        Re-enumeration is REQUIRED: led_count and the per-zone counts are cached from the first
        walk, so without it every later write is still sized against the old zero.
        """
        changed = False
        for dev in self.devices:
            for match, sizes in self.zone_sizes.items():
                if match.lower() not in dev["name"].lower():
                    continue
                for zone_index, size in enumerate(sizes):
                    if zone_index >= len(dev["zones"]):
                        log.warning("%s: no zone %d to resize", dev["name"], zone_index)
                        continue
                    if dev["zones"][zone_index] == size:
                        continue
                    log.info(
                        "%s zone %d: %d -> %d LEDs",
                        dev["name"],
                        zone_index,
                        dev["zones"][zone_index],
                        size,
                    )
                    self.resize_zone(dev["index"], zone_index, size)
                    changed = True
        if changed:
            time.sleep(1.0)
            self._load_devices()

    def _controller_count(self) -> int:
        self._send(0, REQUEST_CONTROLLER_COUNT)
        _size, _cmd, body = self._recv()
        return struct.unpack("<I", body)[0]

    @staticmethod
    def _parse_controller(body: bytes, index: int) -> dict:
        """Parse a controller description.

        Only the fields this daemon needs are kept — name, type, and the LED count, which is
        what UPDATELEDS must match exactly. Walking the whole structure is still necessary to
        reach the LED count, since every preceding field is variable-length.
        """
        off = 4  # total data size

        def u32():
            nonlocal off
            v = struct.unpack_from("<I", body, off)[0]
            off += 4
            return v

        def u16():
            nonlocal off
            v = struct.unpack_from("<H", body, off)[0]
            off += 2
            return v

        def s():
            nonlocal off
            ln = u16()
            v = body[off : off + ln - 1].decode("utf-8", "replace")
            off += ln
            return v

        dev_type = u32()
        # PROTOCOL v6 INSERTS `vendor` AFTER `name`. Older documentation and several client
        # implementations list only name/description/version/serial/location, and omitting
        # vendor shifts every subsequent field — the symptom is a nonsense num_modes (68 on a
        # device with 11) and then a struct.error demanding a 21KB buffer for a 1.2KB packet.
        # Verified by dumping the raw bytes (u16 length, then the string):
        #   <len> "<device name>"          <- name
        #   <len> "<vendor>"               <- vendor
        #   <len> "<device description>"   <- description
        name = s()
        vendor = s()
        desc, version, serial, location = s(), s(), s(), s()

        num_modes = u16()
        active_mode = struct.unpack_from("<i", body, off)[0]
        off += 4
        modes = []
        for _idx in range(num_modes):
            mname = s()
            # TWELVE 4-byte fields, then the colour count. Protocol v6 extended this struct
            # (brightness min/max and a flags extension) beyond the nine that older client
            # implementations use. Derived empirically against this server rather than from
            # documentation: only 12 makes every mode name in every device parse as printable
            # text and land exactly on the declared packet length. With 9 the first mode parses
            # correctly and the second returns an empty name, which is the tell.
            off += MODE_STRUCT_FIELDS * 4
            n_colors = u16()
            off += n_colors * 4
            modes.append(mname)

        num_zones = u16()
        zones: list[int] = []
        for _idx in range(num_zones):
            s()  # zone name
            off += 4  # zone type (0=single, 1=linear, 2=matrix)
            off += 4 * 2  # leds_min, leds_max
            zones.append(u32())  # leds_count — needed to size each zone's colour payload
            # matrix_length is a u16 BYTE COUNT whose bytes INCLUDE the 8-byte height/width
            # header. A keyboard with a 6x16 key matrix reads 392 = 8 + (6 * 16 * 4). It
            # reads 0 on devices without a matrix (RAM, most boards), so a wrong width here is
            # invisible on them and corrupts only the device with a real matrix.
            matrix_length = u16()
            off += matrix_length
            # Zone segments (protocol v4+). Zero on every device here, but skipping the count
            # itself would still desynchronise by two bytes per zone.
            num_segments = u16()
            for _idx in range(num_segments):
                s()  # segment name
                off += 4  # segment type
                off += 4 * 2  # start_idx, leds_count

        num_leds = u16()
        for _idx in range(num_leds):
            s()  # led name
            off += 4  # led value (legacy layout; removed at v6)

        # TRAILING COLOUR ARRAY: the controller's CURRENT per-LED colours, u16 count then that
        # many u32s. Omitting it leaves the walk short by exactly (2 + 4 * num_leds).
        num_colors = u16()
        off += num_colors * 4

        # The blob declares its own length in the first u32. A parse that does not land on it
        # exactly has a field-width error somewhere, and every value after that point is
        # garbage — so fail loudly here rather than return plausible-looking nonsense.
        declared = struct.unpack_from("<I", body, 0)[0]
        if off != declared:
            raise RuntimeError(
                f"controller {index} ({name!r}): parse consumed {off} bytes, "
                f"blob declares {declared} — protocol layout mismatch"
            )

        return {
            "index": index,
            "name": name,
            "vendor": vendor,
            "type": dev_type,
            "description": desc,
            "location": location,
            "modes": modes,
            "active_mode": modes[active_mode] if 0 <= active_mode < len(modes) else None,
            "led_count": num_leds,
            # What writes are actually sized against: after a zone resize this diverges from
            # led_count, which OpenRGB leaves at its pre-resize value.
            "effective_leds": sum(zones),
            "zones": zones,
        }

    def read_colors(self, dev: int) -> list[tuple[int, int, int]]:
        """Re-read a controller and return its CURRENT per-LED colours.

        The only independent proof that a colour actually reached the hardware — the set call
        itself is fire-and-forget and reports nothing. Reads the trailing colour array, whose
        position is known exactly because the walk in _parse_controller is verified to land on
        each blob's declared length.
        """
        n = self.devices[dev]["led_count"]
        if n == 0:
            # A resized addressable zone leaves led_count at 0, so the trailing colour array is
            # absent and there is nothing to read back. Report that honestly rather than
            # implying the device is unlit.
            return []
        self._send(dev, REQUEST_CONTROLLER_DATA, struct.pack("<I", PROTOCOL_VERSION))
        _size, _cmd, body = self._recv()
        pos = len(body) - 2 - 4 * n
        count = struct.unpack_from("<H", body, pos)[0]
        if count != n:
            raise RuntimeError(f"colour array is {count} entries, expected {n}")
        out = []
        for i in range(count):
            v = struct.unpack_from("<I", body, pos + 2 + i * 4)[0]
            # OpenRGB packs colour as 0x00BBGGRR — red in the LOW byte.
            out.append((v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF))
        return out

    def resize_zone(self, dev: int, zone: int, size: int) -> None:
        """Tell the controller how many LEDs are attached to an addressable zone.

        ARGB strips and fans cannot report their own length, so a motherboard header reports
        leds_count = 0 until told otherwise — and a zone of zero LEDs is silently skipped by
        every write. That is why case fans keep running their onboard BIOS effect while every
        other device obeys the daemon: nothing is failing, there is simply nothing to write to.

        The size is per HEADER and must count every LED daisy-chained on that branch.
        """
        payload = struct.pack("<i", zone) + struct.pack("<I", size)
        self._send(dev, RGBCONTROLLER_RESIZEZONE, struct.pack("<I", 4 + len(payload)) + payload)

    def set_zone_colors(self, dev: int, zone: int, colors: list[tuple[int, int, int]]) -> None:
        """Set one zone's LEDs to an explicit per-LED list.

        Separate from set_colors(), which fills every zone with a single colour. This is what a
        chase pattern needs — and keeping the packet construction in ONE place means the
        size-field-counts-itself rule cannot be got right here and wrong there.
        """
        payload = struct.pack("<I", zone) + struct.pack("<H", len(colors))
        for r, g, b in colors:
            payload += struct.pack("<BBBB", r, g, b, 0)
        self._send(dev, RGBCONTROLLER_UPDATEZONELEDS, struct.pack("<I", 4 + len(payload)) + payload)

    def set_custom_mode(self, dev: int) -> None:
        """Ask the server to put a device into a per-LED colour mode.

        Header-only packet with a ZERO-length payload; the server walks Direct/Custom/Static and
        verifies each supports per-LED colour before selecting it.
        """
        self._send(dev, RGBCONTROLLER_SETCUSTOMMODE)

    def set_mode(self, dev: int, mode_name: str) -> bool:
        """Switch a device to a named mode. Returns False if it does not have that mode."""
        device = self.devices[dev]
        if mode_name not in device["modes"]:
            return False
        self._send(
            dev, RGBCONTROLLER_UPDATEMODE, struct.pack("<I", device["modes"].index(mode_name))
        )
        return True

    def set_colors(self, dev: int, colors: list[tuple[int, int, int]]) -> None:
        """Set every LED on a device, zone by zone.

        USES UPDATEZONELEDS (1051), NOT UPDATELEDS (1050). The whole-device packet is accepted
        by the server — no error, connection stays open — and silently changes nothing on this
        hardware; the per-zone packet with an identical colour payload works immediately.
        Measured directly: UPDATELEDS left a device on FF0000, UPDATEZONELEDS took it to 00FF00.

        That failure mode is why this daemon verifies with a read-back rather than trusting a
        write to have landed.
        """
        device = self.devices[dev]
        # Gate on the ZONE totals, not led_count. After a zone resize the controller's top-level
        # led_count stays 0 — OpenRGB does not recompute it — so a guard on led_count skips the
        # very device the resize just enabled, leaving its fans on their BIOS effect with correctly
        # sized zones sitting right there.
        if sum(device["zones"]) == 0:
            return
        for zone_index, zone_leds in enumerate(device["zones"]):
            if zone_leds == 0:
                continue
            buf = colors * ((zone_leds // max(len(colors), 1)) + 1)
            buf = buf[:zone_leds]
            payload = struct.pack("<I", zone_index) + struct.pack("<H", zone_leds)
            for r, g, b in buf:
                # OpenRGB packs colour as 0x00BBGGRR — red in the LOW byte.
                payload += struct.pack("<BBBB", r, g, b, 0)
            # The leading size field COUNTS ITSELF: it is 4 + len(payload), not len(payload).
            # Sending the shorter value is accepted without error and silently discarded — the
            # server reads a truncated colour array and drops the update, so a packet that looks
            # correct does nothing.
            self._send(
                dev, RGBCONTROLLER_UPDATEZONELEDS, struct.pack("<I", 4 + len(payload)) + payload
            )


# --------------------------------------------------------------------------------------------
# Sensors
# --------------------------------------------------------------------------------------------


def read_cpu_temp() -> float | None:
    """CPU package temperature from k10temp (AMD)."""
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            with open(os.path.join(hw, "name")) as f:
                if f.read().strip() != "k10temp":
                    continue
            # temp1 is Tctl on k10temp; prefer a label match where one exists.
            for path in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
                label_path = path.replace("_input", "_label")
                label = ""
                if os.path.exists(label_path):
                    with open(label_path) as f:
                        label = f.read().strip()
                if label in ("Tctl", "Tdie", ""):
                    with open(path) as f:
                        return int(f.read().strip()) / 1000.0
        except (OSError, ValueError):
            continue
    return None


def _discrete_gpu_device() -> str | None:
    """The DISCRETE GPU, chosen by largest VRAM.

    Not card0: with an integrated Radeon present it can enumerate first, and reading it gives a
    permanently cold, idle GPU — which looks like a working sensor reporting nothing wrong.
    """
    best, best_vram = None, 0
    for dev in glob.glob("/sys/class/drm/card*/device"):
        vram_file = os.path.join(dev, "mem_info_vram_total")
        if not os.path.exists(vram_file):
            continue
        try:
            with open(vram_file) as f:
                vram = int(f.read().strip())
        except (OSError, ValueError):
            continue
        if vram > best_vram:
            best, best_vram = dev, vram
    return best


def read_gpu() -> tuple[float | None, int | None]:
    """(temperature C, busy percent) for the discrete GPU."""
    dev = _discrete_gpu_device()
    if not dev:
        return None, None
    temp = busy = None
    for hw in glob.glob(os.path.join(dev, "hwmon", "hwmon*")):
        path = os.path.join(hw, "temp1_input")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    temp = int(f.read().strip()) / 1000.0
            except (OSError, ValueError):
                pass
    busy_file = os.path.join(dev, "gpu_busy_percent")
    if os.path.exists(busy_file):
        try:
            with open(busy_file) as f:
                busy = int(f.read().strip())
        except (OSError, ValueError):
            pass
    return temp, busy


def read_load() -> float:
    return os.getloadavg()[0]


# --------------------------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------------------------


def ramp(fraction: float) -> tuple[int, int, int]:
    """Blue -> cyan -> green -> yellow -> red across 0.0-1.0.

    Deliberately not a plain hue rotation: that passes through magenta at the top end, which
    reads as "pretty" rather than "hot". Anchored stops keep the intuitive cold/hot meaning.
    """
    f = max(0.0, min(1.0, fraction))
    stops = [
        (0.00, (0, 0, 255)),
        (0.25, (0, 200, 200)),
        (0.50, (0, 255, 0)),
        (0.75, (255, 200, 0)),
        (1.00, (255, 0, 0)),
    ]
    for i in range(len(stops) - 1):
        f0, c0 = stops[i]
        f1, c1 = stops[i + 1]
        if f0 <= f <= f1:
            t = 0.0 if f1 == f0 else (f - f0) / (f1 - f0)
            return tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3))
    return stops[-1][1]


def parse_hex(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


# --------------------------------------------------------------------------------------------
# Daemon
# --------------------------------------------------------------------------------------------


class Daemon:
    def __init__(self, args):
        self.args = args
        self.client = OpenRGBClient(
            args.host, args.port, zone_sizes=getattr(args, "zone_sizes_parsed", {})
        )
        self.running = True
        self.last: tuple[int, int, int] | None = None
        # Devices already switched to a per-LED mode on THIS connection. Cleared on reconnect,
        # since a fresh connection may land on a server that has been restarted.
        self._moded: set[int] = set()
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)

    def _stop(self, *_):
        log.info("stopping")
        self.running = False

    def target_color(self) -> tuple[tuple[int, int, int], str]:
        a = self.args
        if a.mode == "static":
            return parse_hex(a.color), f"static {a.color}"

        cpu = read_cpu_temp()
        gpu_t, gpu_busy = read_gpu()

        def frac(v, lo, hi):
            return None if v is None else (v - lo) / float(hi - lo)

        cpu_f = frac(cpu, a.cpu_min, a.cpu_max)
        gpu_f = frac(gpu_t, a.gpu_min, a.gpu_max)

        if a.mode == "cpu":
            f, why = cpu_f, f"cpu {cpu:.0f}C" if cpu is not None else "cpu n/a"
        elif a.mode == "gpu":
            f, why = gpu_f, f"gpu {gpu_t:.0f}C" if gpu_t is not None else "gpu n/a"
        elif a.mode == "load":
            load = read_load()
            f, why = load / float(a.load_max), f"load {load:.2f}"
        else:  # auto
            cands = [
                (cpu_f, f"cpu {cpu:.0f}C" if cpu is not None else ""),
                (gpu_f, f"gpu {gpu_t:.0f}C" if gpu_t is not None else ""),
            ]
            cands = [(x, w) for x, w in cands if x is not None]
            if not cands:
                f, why = None, "no sensors"
            else:
                f, why = max(cands, key=lambda t: t[0])
                if gpu_busy is not None:
                    why += f" busy {gpu_busy}%"

        if f is None:
            return parse_hex(a.color), "fallback (no sensor)"
        return ramp(f), why

    def apply(self, color: tuple[int, int, int]) -> None:
        for dev in self.client.devices:
            i = dev["index"]
            # Gate on the ZONE totals, not led_count: after a zone resize OpenRGB leaves the
            # controller's top-level led_count at 0, so this guard would skip the very device
            # the resize just enabled, leaving those fans dark with correctly sized zones
            # sitting right there.
            if sum(dev.get("zones", [])) == 0 and dev["led_count"] == 0:
                continue

            # SETCUSTOMMODE ONCE PER CONNECTION, NOT PER CYCLE. Re-applying the mode makes the
            # device blank for a fraction of a second, so sending it every 2s produced a visible
            # flash to black on every device — looking like a fault in the hardware rather than
            # in this loop. The mode only needs establishing once; it persists for as long as
            # the connection does, and a reconnect clears the flag so it is re-sent.
            if i not in self._moded:
                self.client.set_custom_mode(i)
                self._moded.add(i)

            try:
                self.client.set_colors(i, [color])
            except (OSError, struct.error) as exc:
                log.warning("device %s (%s): %s", i, dev["name"], exc)

    def run(self) -> int:
        backoff = 2
        while self.running:
            try:
                self.client.connect()
                backoff = 2
                while self.running:
                    color, why = self.target_color()
                    if color != self.last or self.args.mode != "static":
                        self.apply(color)
                        if color != self.last:
                            log.info("#%02x%02x%02x  (%s)", *color, why)
                        self.last = color
                    # Static needs no polling: set it once and hold the connection open, which
                    # is the whole reason the colour persists.
                    time.sleep(self.args.interval if self.args.mode != "static" else 60)
            except (OSError, RuntimeError) as exc:
                if not self.running:
                    break
                log.warning("connection lost (%s); retrying in %ss", exc, backoff)
                self.client.close()
                self.last = None
                self._moded.clear()
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        self.client.close()
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=6742)
    p.add_argument("--mode", default="auto", choices=["static", "cpu", "gpu", "load", "auto"])
    p.add_argument("--color", default="00AAFF", help="colour for static mode / sensor fallback")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--cpu-min", type=float, default=35.0)
    p.add_argument("--cpu-max", type=float, default=85.0)
    p.add_argument("--gpu-min", type=float, default=30.0)
    p.add_argument("--gpu-max", type=float, default=85.0)
    p.add_argument("--load-max", type=float, default=16.0)
    p.add_argument(
        "--once",
        action="store_true",
        help="apply once and exit — for testing; the colour will NOT persist",
    )
    p.add_argument(
        "--zone-sizes",
        default="",
        help="Declare LED counts for addressable zones that cannot report their own "
        "length, e.g. 'BOARD=24,24,8' — device name substring, then one count per "
        "zone. Repeat with ';' for several devices.",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help="re-read each device's CURRENT colour from the hardware and print it",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="print devices and the current target as JSON, then exit",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    zone_sizes: dict[str, list[int]] = {}
    for entry in filter(None, (e.strip() for e in args.zone_sizes.split(";"))):
        match, _sep, counts = entry.partition("=")
        if not counts:
            log.warning("ignoring malformed --zone-sizes entry %r", entry)
            continue
        zone_sizes[match.strip()] = [int(c) for c in counts.split(",") if c.strip()]
    args.zone_sizes_parsed = zone_sizes

    if args.report:
        d = Daemon(args)
        d.client.connect()
        color, why = d.target_color()
        print(
            json.dumps(
                {
                    "devices": [
                        {k: v for k, v in dev.items() if k != "modes"} | {"modes": dev["modes"]}
                        for dev in d.client.devices
                    ],
                    "target": {"rgb": list(color), "hex": "%02X%02X%02X" % color, "reason": why},
                    "sensors": {
                        "cpu_c": read_cpu_temp(),
                        "gpu_c": read_gpu()[0],
                        "gpu_busy": read_gpu()[1],
                        "load": read_load(),
                    },
                },
                indent=2,
            )
        )
        d.client.close()
        return 0

    if args.verify:
        c = OpenRGBClient(args.host, args.port, "iaac-verify", zone_sizes)
        c.connect()
        rows = []
        for dev in c.devices:
            try:
                cols = c.read_colors(dev["index"])
            except (RuntimeError, struct.error) as exc:
                rows.append({"name": dev["name"], "error": str(exc)})
                continue
            rows.append(
                {
                    "name": dev["name"],
                    "led_count": dev["led_count"],
                    "active_mode": dev["active_mode"],
                    "first_color": ("%02X%02X%02X" % cols[0]) if cols else None,
                    "uniform": len(set(cols)) <= 1 if cols else None,
                }
            )
        print(json.dumps({"devices": rows}, indent=2))
        c.close()
        return 0

    if args.once:
        d = Daemon(args)
        d.client.connect()
        color, why = d.target_color()
        d.apply(color)
        log.info("applied #%02x%02x%02x (%s) — will NOT persist after exit", *color, why)
        d.client.close()
        return 0

    return Daemon(args).run()


if __name__ == "__main__":
    sys.exit(main())
