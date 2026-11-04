#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for steam_guard.py's decision logic. Stdlib only.

Each guard is tested in BOTH directions: a case that
must make it act, and a near-miss that must not. A watchdog whose restart branch cannot be
reached reports "healthy" forever, which is indistinguishable from working.
"""

from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from steam_guard import (  # noqa: E402
    Config,
    acts,
    suspend_stuck,
    Observation,
    State,
    classify,
    decide,
    listening_on,
    manual_allowed,
    peer_allowed,
    problems_of,
)

CFG = Config(unhealthy_for=180, startup_grace=300, update_grace=900, max_restarts=6, window=10800)
STEAM = "/var/home/user/.local/share/Steam/ubuntu12_32/steam"


def obs(**kw) -> Observation:
    base = dict(
        session_active=True,
        steam_age=3600.0,
        updater_age=None,
        webhelper=True,
        listening=True,
    )
    base.update(kw)
    return Observation(**base)


class Classify(unittest.TestCase):
    def test_client_updater_webhelper(self):
        self.assertEqual(classify([STEAM, "-gamepadui"]), "steam")
        self.assertEqual(classify([STEAM, "-child-update-ui", "-gamepadui"]), "updater")
        self.assertEqual(classify(["./steamwebhelper", "-nocrashdialog"]), "webhelper")

    def test_near_misses_are_not_steam(self):
        # steam.sh, the reaper and Proton's steam.exe all mention steam; none is the client.
        self.assertIsNone(classify(["bash", "/var/home/user/.local/share/Steam/steam.sh"]))
        self.assertIsNone(
            classify(
                [
                    "/var/home/user/.local/share/Steam/ubuntu12_32/reaper",
                    "SteamLaunch",
                ]
            )
        )
        self.assertIsNone(classify(["c:\\windows\\system32\\steam.exe"]))
        # This process's own argv must never classify as Steam (self-match trap).
        self.assertIsNone(
            classify(
                [
                    "/usr/bin/python3",
                    "/home/x/.local/bin/iaac-steam-guard",
                    "--port",
                    "8090",
                ]
            )
        )
        self.assertIsNone(classify([]))


class Listening(unittest.TestCase):
    HDR = "  sl  local_address rem_address   st\n"

    def test_listen_on_27036(self):
        table = self.HDR + "   0: 00000000:699C 00000000:0000 0A 00000000\n"
        self.assertTrue(listening_on(27036, [table]))

    def test_established_or_other_port_is_not_listening(self):
        established = self.HDR + "   0: 030200C0:699C 040200C0:D431 01 00000000\n"
        other_port = self.HDR + "   0: 00000000:699D 00000000:0000 0A 00000000\n"
        remote_port = self.HDR + "   0: 030200C0:D431 040200C0:699C 0A 00000000\n"
        self.assertFalse(listening_on(27036, [established, other_port, remote_port]))


class Problems(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(problems_of(obs(), CFG), [])

    def test_not_in_game_mode_is_none_not_a_fault(self):
        self.assertIsNone(problems_of(obs(session_active=False, steam_age=None), CFG))

    def test_dead_client(self):
        self.assertEqual(
            problems_of(obs(steam_age=None, webhelper=False, listening=False), CFG),
            ["steam client not running"],
        )

    def test_dead_webhelper(self):
        self.assertIn("steamwebhelper not running", problems_of(obs(webhelper=False), CFG))

    def test_discovery_closed_after_grace(self):
        self.assertTrue(problems_of(obs(listening=False, steam_age=301), CFG))

    def test_discovery_closed_during_startup_is_tolerated(self):
        self.assertEqual(problems_of(obs(listening=False, steam_age=299), CFG), [])

    def test_young_update_is_tolerated_old_one_is_not(self):
        self.assertEqual(
            problems_of(obs(steam_age=None, webhelper=False, updater_age=899), CFG), []
        )
        self.assertTrue(problems_of(obs(steam_age=None, webhelper=False, updater_age=901), CFG))


class Decide(unittest.TestCase):
    BAD = ["steam client not running"]

    def test_restarts_only_after_sustained_failure(self):
        st = State()
        self.assertEqual(decide(1000, self.BAD, st, CFG), "waiting")
        self.assertEqual(decide(1179, self.BAD, st, CFG), "waiting")
        self.assertEqual(decide(1180, self.BAD, st, CFG), "restart")

    def test_recovery_resets_the_clock(self):
        st = State()
        decide(1000, self.BAD, st, CFG)
        self.assertEqual(decide(1100, [], st, CFG), "healthy")
        self.assertEqual(decide(1200, self.BAD, st, CFG), "waiting")

    def test_grace_holds_off(self):
        st = State(grace_until=2000)
        self.assertEqual(decide(1999, self.BAD, st, CFG), "grace")

    def test_idle_never_restarts(self):
        st = State(unhealthy_since=0)
        self.assertEqual(decide(99999, None, st, CFG), "idle")

    def test_rate_limit_six_in_three_hours(self):
        now = 50000.0
        st = State(
            unhealthy_since=now - 1000,
            auto_restarts=[now - 60 * i for i in range(1, 7)],
        )
        self.assertEqual(decide(now, self.BAD, st, CFG), "rate_limited")

    def test_fifth_restart_still_allowed_and_old_ones_expire(self):
        now = 50000.0
        st = State(
            unhealthy_since=now - 1000,
            auto_restarts=[now - 60 * i for i in range(1, 6)],
        )
        self.assertEqual(decide(now, self.BAD, st, CFG), "restart")
        st = State(unhealthy_since=now - 1000, auto_restarts=[now - 10801] * 6)
        self.assertEqual(decide(now, self.BAD, st, CFG), "restart")


class Gates(unittest.TestCase):
    def test_peer_allowlist(self):
        allow = {"192.0.2.4", "198.51.100.4"}
        self.assertTrue(peer_allowed("192.0.2.4", allow))
        self.assertTrue(peer_allowed("::ffff:198.51.100.4", allow))
        self.assertTrue(peer_allowed("127.0.0.1", allow))
        self.assertFalse(peer_allowed("192.0.2.40", allow))  # prefix, not membership
        self.assertFalse(peer_allowed("192.0.2.5", allow))

    def test_manual_cooldown(self):
        st = State(manual_restarts=[1000.0])
        self.assertFalse(manual_allowed(1059, st, CFG))
        self.assertTrue(manual_allowed(1060, st, CFG))
        self.assertTrue(manual_allowed(0, State(), CFG))


def _ts(stamp: str) -> float:
    return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))


# The shape of Steam's webhelper_js.txt lines for a deliberate Sleep press.
PREPARE = [
    "[2000-01-02 09:53:30] SteamUI: INFO: SuspendResume: Received suspend request",
    "[2000-01-02 09:53:30] SteamUI: INFO: SuspendResume: OnPrepareForSuspendProgress [object Object]",
    "[2000-01-02 09:53:30] SteamUI: INFO: SuspendResume: PrepareForSystemSuspend succeeded",
]
IGNORED = [
    "[2000-01-02 08:54:04] SteamUI: INFO: SuspendResume: Received suspend request",
    "[2000-01-02 08:54:04] SteamUI: WARNING: SuspendResume: Ignoring suspend request while a "
    "suspend operation is in progress: 1",
]


class StuckSuspend(unittest.TestCase):
    STARTED = _ts("2000-01-02 09:43:21")

    def test_prepared_and_masked_is_stuck_after_settling(self):
        why = suspend_stuck(PREPARE, self.STARTED, _ts("2000-01-02 09:55:00"), sleep_masked=True)
        self.assertIsNotNone(why)
        self.assertIn("09:53:30", why)

    def test_prepared_but_not_settled_is_not_yet_stuck(self):
        # Within `settle` the suspend may still be in flight; judging it would race logind.
        self.assertIsNone(
            suspend_stuck(PREPARE, self.STARTED, _ts("2000-01-02 09:53:50"), sleep_masked=True)
        )

    def test_prepared_with_sleep_unmasked_is_normal(self):
        # Unmasked, a prepare is an ordinary suspend that will resume: never a restart reason.
        self.assertIsNone(
            suspend_stuck(PREPARE, self.STARTED, _ts("2000-01-02 10:30:00"), sleep_masked=False)
        )

    def test_lines_before_this_steam_start_do_not_count(self):
        # The file spans restarts; the prepare belongs to the client that was restarted away.
        later_start = _ts("2000-01-02 10:00:00")
        self.assertIsNone(
            suspend_stuck(PREPARE, later_start, _ts("2000-01-02 10:30:00"), sleep_masked=True)
        )

    def test_steam_saying_it_ignored_a_request_is_stuck_even_unmasked(self):
        started = _ts("2000-01-01 19:31:41")
        why = suspend_stuck(IGNORED, started, _ts("2000-01-02 08:55:00"), sleep_masked=False)
        self.assertIsNotNone(why)
        self.assertIn("08:54:04", why)

    def test_unrelated_and_unstamped_lines_are_not_stuck(self):
        lines = [
            "[2000-01-02 09:52:11] SteamUI: INFO: onGlobalMenuButtonDown SP BPM_uid0",
            "SuspendResume: PrepareForSystemSuspend succeeded",  # no timestamp: ignored
        ]
        self.assertIsNone(
            suspend_stuck(lines, self.STARTED, _ts("2000-01-02 10:30:00"), sleep_masked=True)
        )

    def test_it_is_a_problem_in_game_mode(self):
        self.assertEqual(
            problems_of(obs(suspend_stuck="Steam UI stuck mid-suspend (x)"), CFG),
            ["Steam UI stuck mid-suspend (x)"],
        )


class Acts(unittest.TestCase):
    STUCK = ["Steam UI stuck mid-suspend (prepared at 09:53:30)"]
    DEAD = ["steam client not running"]

    def test_observe_mode_acts_on_stuck_suspend_only_when_allowed(self):
        self.assertTrue(acts(self.STUCK, Config(restart_on_stuck_suspend=True)))
        self.assertFalse(acts(self.STUCK, Config(restart_on_stuck_suspend=False)))

    def test_observe_mode_never_acts_on_other_problems(self):
        # The exemption is for the PROVEN cause only; a dead client stays observe-only.
        self.assertFalse(acts(self.DEAD, Config(restart_on_stuck_suspend=True)))
        self.assertFalse(acts(self.STUCK + self.DEAD, Config(restart_on_stuck_suspend=True)))
        self.assertFalse(acts([], Config(restart_on_stuck_suspend=True)))

    def test_enforce_mode_acts_on_everything(self):
        self.assertTrue(acts(self.DEAD, Config(enforce=True)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
