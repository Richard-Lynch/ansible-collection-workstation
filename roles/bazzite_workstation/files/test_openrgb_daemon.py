# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for openrgb_daemon.py's brightness scaling, breathe curve and write cadence. Stdlib only.

The cadence tests drive the real loops against a fake client and a fake clock, because the
property that matters is HOW OFTEN the hardware is written: with breathing off the daemon must
write exactly as it did before brightness existed, and with it on a tick that changes nothing
must send nothing.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openrgb_daemon  # noqa: E402
from openrgb_daemon import Daemon, breathe_level, scale  # noqa: E402


class ScaleTest(unittest.TestCase):
    def test_full_brightness_is_the_colour_unchanged(self):
        self.assertEqual(scale((0xFF, 0x00, 0x80), 100), (0xFF, 0x00, 0x80))

    def test_twenty_percent_of_ff0080(self):
        # 255 * 0.2 = 51 (0x33), 128 * 0.2 = 25.6 -> 26 (0x1A): the colour the box ran
        # by hand before brightness existed.
        self.assertEqual(scale((0xFF, 0x00, 0x80), 20), (0x33, 0x00, 0x1A))

    def test_zero_is_off(self):
        self.assertEqual(scale((0xFF, 0xFF, 0xFF), 0), (0, 0, 0))

    def test_out_of_range_is_clamped(self):
        self.assertEqual(scale((200, 100, 50), 150), (200, 100, 50))
        self.assertEqual(scale((200, 100, 50), -5), (0, 0, 0))

    def test_hue_holds_at_the_low_end(self):
        # 12.5% is the bottom of a 20 +/- 7.5 breath. The red:blue ratio of FF0080 is ~2:1 and
        # must stay ~2:1, with green still exactly off, or the colour visibly shifts as it dims.
        r, g, b = scale((0xFF, 0x00, 0x80), 12.5)
        self.assertEqual(g, 0)
        self.assertAlmostEqual(r / b, 0xFF / 0x80, delta=0.1)


class BreatheLevelTest(unittest.TestCase):
    def test_depth_zero_is_constant(self):
        for t in (0.0, 0.7, 1.0, 2.0, 3.3):
            self.assertEqual(breathe_level(20, 0, 4, t), 20)

    def test_sine_peaks_and_troughs(self):
        self.assertAlmostEqual(breathe_level(20, 7.5, 4, 0.0), 20.0)
        self.assertAlmostEqual(breathe_level(20, 7.5, 4, 1.0), 27.5)
        self.assertAlmostEqual(breathe_level(20, 7.5, 4, 2.0), 20.0, places=6)
        self.assertAlmostEqual(breathe_level(20, 7.5, 4, 3.0), 12.5)

    def test_period_repeats(self):
        self.assertAlmostEqual(
            breathe_level(20, 7.5, 4, 1.0), breathe_level(20, 7.5, 4, 5.0)
        )

    def test_clamped_at_both_ends(self):
        self.assertEqual(breathe_level(95, 10, 4, 1.0), 100.0)
        self.assertEqual(breathe_level(5, 10, 4, 3.0), 0.0)

    def test_non_positive_period_is_constant(self):
        self.assertEqual(breathe_level(20, 7.5, 0, 1.0), 20)


class FakeClient:
    def __init__(self):
        self.devices = [{"index": 0, "name": "fake", "led_count": 4, "zones": [4]}]
        self.writes: list[tuple[int, int, int]] = []
        self.custom_modes = 0

    def set_custom_mode(self, dev):
        self.custom_modes += 1

    def set_colors(self, dev, colors):
        self.writes.append(colors[0])


class FakeClock:
    """time.monotonic/time.sleep that advance a counter and stop the daemon after `until`."""

    def __init__(self, daemon, until):
        self.now, self.daemon, self.until = 0.0, daemon, until
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        if self.now >= self.until:
            self.daemon.running = False


def make_daemon(**overrides):
    args = argparse.Namespace(
        host="127.0.0.1",
        port=6742,
        mode="static",
        color="FF0080",
        interval=2.0,
        cpu_min=35.0,
        cpu_max=85.0,
        gpu_min=30.0,
        gpu_max=85.0,
        load_max=16.0,
        brightness=100.0,
        breathe_depth=0.0,
        breathe_period=4.0,
        breathe_rate=20.0,
        zone_sizes_parsed={},
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    with mock.patch.object(openrgb_daemon.signal, "signal"):
        d = Daemon(args)
    d.client = FakeClient()
    return d


def drive(d, loop, until):
    clock = FakeClock(d, until)
    with (
        mock.patch.object(openrgb_daemon.time, "monotonic", clock.monotonic),
        mock.patch.object(d, "_sleep", clock.sleep),
    ):
        loop()
    return clock


class StopTest(unittest.TestCase):
    def test_sigterm_ends_the_static_hold_at_once(self):
        # The REAL handler and the REAL wait, in the main thread, as under systemd: a timer
        # sends SIGTERM to this process one tenth of a second into static mode's 60 s hold.
        # time.sleep would resume after the handler and hold for the full minute.
        old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        try:
            d = make_daemon()
            signal.signal(signal.SIGTERM, d._stop)
            timer = threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGTERM))
            timer.start()
            t0 = time.monotonic()
            d._run_steady()
            elapsed = time.monotonic() - t0
            timer.join()
        finally:
            for s, h in old.items():
                signal.signal(s, h)
        self.assertFalse(d.running)
        self.assertLess(elapsed, 5.0)

    def test_breathing_stops_within_a_tick(self):
        d = make_daemon(breathe_depth=7.5)
        threading.Timer(0.1, d._stop).start()
        t0 = time.monotonic()
        d._run_breathing()
        self.assertLess(time.monotonic() - t0, 1.0)


class SocketErrorTest(unittest.TestCase):
    def test_a_dead_socket_reaches_the_reconnect(self):
        d = make_daemon()

        def broken(dev, colors):
            raise BrokenPipeError("server gone")

        d.client.set_colors = broken
        with self.assertRaises(OSError):
            d.apply((1, 2, 3))

    def test_a_malformed_packet_stays_a_per_device_warning(self):
        d = make_daemon()

        def malformed(dev, colors):
            raise openrgb_daemon.struct.error("bad pack")

        d.client.set_colors = malformed
        with self.assertLogs("openrgb-daemon", level="WARNING"):
            d.apply((1, 2, 3))


class ArgumentBoundsTest(unittest.TestCase):
    def refused(self, *argv):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as cm:
            openrgb_daemon.parse_args(list(argv))
        self.assertEqual(cm.exception.code, 2)

    def test_defaults_are_neutral(self):
        a = openrgb_daemon.parse_args([])
        self.assertEqual((a.brightness, a.breathe_depth), (100.0, 0.0))

    def test_in_range_values_parse(self):
        a = openrgb_daemon.parse_args(
            ["--brightness", "20", "--breathe-depth", "7.5", "--breathe-rate", "100"]
        )
        self.assertEqual(
            (a.brightness, a.breathe_depth, a.breathe_rate), (20.0, 7.5, 100.0)
        )

    def test_out_of_range_values_are_refused(self):
        self.refused("--brightness", "101")
        self.refused("--brightness", "nan")
        self.refused("--breathe-depth", "-1")
        self.refused("--breathe-rate", "0")
        self.refused("--breathe-rate", "1e9")
        self.refused("--breathe-rate", "inf")
        self.refused("--breathe-period", "0")
        self.refused("--breathe-period", "3601")


class SteadyCadenceTest(unittest.TestCase):
    def test_static_writes_once_and_scaled(self):
        d = make_daemon(brightness=20.0)
        clock = drive(d, d._run_steady, until=600)
        self.assertEqual(d.client.writes, [(0x33, 0x00, 0x1A)])
        self.assertEqual(d.client.custom_modes, 1)
        # The 60s hold is unchanged by brightness.
        self.assertTrue(all(s == 60 for s in clock.sleeps))

    def test_sensor_mode_writes_once_per_interval(self):
        d = make_daemon(mode="auto", brightness=50.0)
        with mock.patch.object(
            Daemon, "target_color", return_value=((200, 100, 0), "cpu 40C")
        ):
            clock = drive(d, d._run_steady, until=20)
        self.assertEqual(len(d.client.writes), 10)
        self.assertEqual(set(d.client.writes), {(100, 50, 0)})
        self.assertTrue(all(s == 2.0 for s in clock.sleeps))

    def test_run_takes_the_steady_loop_when_depth_is_zero(self):
        d = make_daemon()
        d.client.connect = lambda: None
        d.client.close = lambda: None
        with (
            mock.patch.object(
                Daemon, "_run_steady", side_effect=lambda: setattr(d, "running", False)
            ) as steady,
            mock.patch.object(Daemon, "_run_breathing") as breathing,
        ):
            d.run()
        steady.assert_called_once()
        breathing.assert_not_called()


class BreathingCadenceTest(unittest.TestCase):
    def test_static_breathes_around_the_base_brightness(self):
        d = make_daemon(brightness=20.0, breathe_depth=7.5, breathe_period=4.0)
        drive(d, d._run_breathing, until=8)
        reds = [w[0] for w in d.client.writes]
        # 255 * 12.5% = 32 at the trough, 255 * 27.5% = 70 at the peak.
        self.assertLessEqual(min(reds), 33)
        self.assertGreaterEqual(min(reds), 31)
        self.assertGreaterEqual(max(reds), 69)
        self.assertLessEqual(max(reds), 71)
        self.assertTrue(all(w[1] == 0 for w in d.client.writes))
        self.assertEqual(d.client.custom_modes, 1)

    def test_a_tick_that_changes_nothing_sends_nothing(self):
        d = make_daemon(brightness=20.0, breathe_depth=7.5, breathe_period=4.0)
        clock = drive(d, d._run_breathing, until=8)
        self.assertLess(len(d.client.writes), len(clock.sleeps))
        for a, b in zip(d.client.writes, d.client.writes[1:]):
            self.assertNotEqual(a, b)

    def test_sensors_are_read_per_interval_not_per_tick(self):
        d = make_daemon(
            mode="auto", brightness=20.0, breathe_depth=7.5, breathe_period=4.0
        )
        with mock.patch.object(
            Daemon, "target_color", return_value=((255, 0, 128), "cpu 40C")
        ) as target:
            clock = drive(d, d._run_breathing, until=10)
        self.assertGreater(len(clock.sleeps), 150)  # ~20 ticks a second
        self.assertLessEqual(target.call_count, 6)  # one per 2s interval

    def test_static_reads_its_colour_once(self):
        d = make_daemon(brightness=20.0, breathe_depth=7.5)
        with mock.patch.object(
            Daemon, "target_color", return_value=((255, 0, 128), "static FF0080")
        ) as target:
            drive(d, d._run_breathing, until=10)
        self.assertEqual(target.call_count, 1)


if __name__ == "__main__":
    unittest.main()
