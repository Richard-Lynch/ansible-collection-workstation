#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Steam guard: restart the Game Mode Steam session when Steam is DEAD, and on request.

MANAGED BY ANSIBLE — roles/bazzite_workstation/files/steam_guard.py. Edits here are overwritten.

Two jobs in one small process, because both need the same three things — a way to look at Steam,
a way to restart it, and ONE shared record of restarts so neither can hide the other's:

  WATCHDOG   every --interval seconds, look at Steam. Restart the session only when Steam is
             unambiguously broken (client gone, web helper gone, or Remote Play discovery closed)
             for --unhealthy-for seconds in a row, and never more than --max-restarts times in
             --window seconds. Acts ONLY while the Game Mode session unit is active: a machine
             someone switched to Desktop Mode is not broken, and fighting them would be.

  STUCK SUSPEND  Steam's UI prepares for an idle/menu suspend BEFORE asking logind, and only
             recovers on the resume. With the sleep targets masked (bazzite_sleep_inhibit) logind
             refuses, no resume ever comes, and the main Big Picture page stays BLACK while menus
             and overlays still draw (reproducible by pressing Sleep).
             Detected from Steam's own webhelper_js.txt; with --restart-on-stuck-suspend this ONE
             signature restarts Steam even in observe mode, because the fault is now understood.

  ENDPOINT   POST /steam/restart  — restart on request (the Steam Deck tile). Allowed only from
                                    --allow addresses; a short cooldown stops a double press.
             GET  /healthz        — what the guard sees, as JSON. The tile polls this to report a
                                    real outcome instead of "request sent".

WHAT IT DELIBERATELY DOES NOT DO: kill a running game. A stuck launch and a game left paused look
the same from outside — GPU busy reads about the same WITH a stuck launch and after killing it —
so there is no safe automatic signal. That stays a one-press tile decision.

WHY THE ALLOWLIST IS ENFORCED HERE, not in firewalld. A Bazzite machine's NIC sits in Fedora's
`FedoraWorkstation` zone, which admits every port 1025-65535 from anywhere. A firewalld rich rule for this
port would read as an allowlist and restrict nothing.

NO PRIVILEGES. It runs as the session user in a --user unit, so restarting
gamescope-session-plus@steam is the user's own `systemctl --user restart`, and every read below
(/proc, /proc/net/tcp) is unprivileged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Steam's Remote Play DISCOVERY port: if this is not listening, a client sees no host to stream
# from.
DISCOVERY_PORT = 27036
TCP_LISTEN = "0A"


# --------------------------------------------------------------------------------------------
# OBSERVING
# --------------------------------------------------------------------------------------------


@dataclass
class Observation:
    session_active: bool
    steam_age: float | None  # seconds since the Steam client started; None = not running
    updater_age: float | None  # seconds since a Steam self-update child started; None = none
    webhelper: bool
    listening: bool
    suspend_stuck: str | None = None  # why Steam's UI is stuck mid-suspend; None = it is not


# Steam's UI log lines, verbatim in shape (webhelper_js.txt):
#   [YYYY-MM-DD hh:mm:ss] SteamUI: INFO: SuspendResume: PrepareForSystemSuspend succeeded
#   [YYYY-MM-DD hh:mm:ss] SteamUI: WARNING: SuspendResume: Ignoring suspend request while a
#                         suspend operation is in progress: 1
_TS = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] ")
PREPARED = "SuspendResume: PrepareForSystemSuspend succeeded"
IGNORING = "SuspendResume: Ignoring suspend request while a suspend operation is in progress"


def _read(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _proc_age(pid: str, uptime: float, hz: int) -> float | None:
    # Field 22 of /proc/<pid>/stat is the start time in clock ticks since boot. Split AFTER the
    # last ')' because the command name in field 2 may itself contain spaces or parentheses.
    stat = _read(f"/proc/{pid}/stat")
    if ")" not in stat:
        return None
    fields = stat.rsplit(")", 1)[1].split()
    try:
        return uptime - int(fields[19]) / hz
    except (IndexError, ValueError):
        return None


def listening_on(port: int, tables: list[str]) -> bool:
    """True when any /proc/net/tcp{,6} table shows a LISTEN socket on `port`."""
    want = f"{port:04X}"
    for table in tables:
        for line in table.splitlines()[1:]:
            cols = line.split()
            if len(cols) > 3 and cols[1].rsplit(":", 1)[-1] == want and cols[3] == TCP_LISTEN:
                return True
    return False


def suspend_stuck(
    lines: list[str], steam_started: float, now: float, sleep_masked: bool, settle: float = 60
) -> str | None:
    """Why Steam's UI is stuck mid-suspend, or None. Pure: lines are webhelper_js.txt's tail.

    Only lines stamped AFTER the running client started count — the file is appended across
    restarts, and a restart is exactly what clears this state. Timestamps are the box's LOCAL
    time, as Steam writes them.

    Stuck when either:
      * Steam says so: it ignored a later suspend request because one is "in progress"; or
      * Steam prepared for a suspend at least `settle` seconds ago AND the sleep targets are
        masked — the suspend cannot have happened, so no resume can ever arrive. (Unmasked, a
        prepare is normal: the box sleeps and resumes, and is NOT judged stuck here.)
    """
    prepared = ignored = None
    for line in lines:
        m = _TS.match(line)
        if not m:
            continue
        try:
            ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if ts < steam_started:
            continue
        if PREPARED in line:
            prepared = ts
        elif IGNORING in line:
            ignored = ts
    if ignored is not None:
        return f"Steam UI stuck mid-suspend (ignored a suspend request at {time.strftime('%H:%M:%S', time.localtime(ignored))})"
    if prepared is not None and sleep_masked and now - prepared >= settle:
        return f"Steam UI stuck mid-suspend (prepared at {time.strftime('%H:%M:%S', time.localtime(prepared))}; sleep targets masked, so no resume can come)"
    return None


def _tail(path: str, nbytes: int = 262144) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - nbytes))
            return fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def classify(argv: list[str]) -> str | None:
    """Name a process by its argv: 'steam', 'updater', 'webhelper', or None.

    Matches on the EXECUTABLE (argv[0]) rather than searching the whole command line, so this
    process — whose own argv never names those binaries — can never match itself (a query must
    not match its own trace).
    """
    if not argv:
        return None
    exe = argv[0]
    if exe.endswith("/ubuntu12_32/steam"):
        # The self-updater is the same binary with -child-update-ui; it runs while Steam swaps
        # builds, and the main client is legitimately absent for part of that.
        return "updater" if "-child-update-ui" in argv else "steam"
    if os.path.basename(exe) == "steamwebhelper":
        return "webhelper"
    return None


def observe(unit: str, steam_log: str = "") -> Observation:
    uptime = float(_read("/proc/uptime").split()[0] or 0)
    hz = os.sysconf("SC_CLK_TCK")
    steam_age = updater_age = None
    webhelper = False
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        argv = [a for a in _read(f"/proc/{pid}/cmdline").split("\0") if a]
        kind = classify(argv)
        if kind == "steam":
            age = _proc_age(pid, uptime, hz)
            steam_age = age if steam_age is None or (age or 0) > steam_age else steam_age
        elif kind == "updater":
            updater_age = _proc_age(pid, uptime, hz)
        elif kind == "webhelper":
            webhelper = True
    active = (
        subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        == "active"
    )
    tables = [_read("/proc/net/tcp"), _read("/proc/net/tcp6")]
    stuck = None
    if steam_log and steam_age is not None:
        masked = (
            subprocess.run(
                ["systemctl", "is-enabled", "suspend.target"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            == "masked"
        )
        now = time.time()
        stuck = suspend_stuck(_tail(steam_log), now - steam_age, now, masked)
    return Observation(
        active, steam_age, updater_age, webhelper, listening_on(DISCOVERY_PORT, tables), stuck
    )


# --------------------------------------------------------------------------------------------
# DECIDING — pure functions, unit-tested in test_steam_guard.py
# --------------------------------------------------------------------------------------------


@dataclass
class Config:
    interval: float = 30
    unhealthy_for: float = 180
    startup_grace: float = 300
    update_grace: float = 900
    max_restarts: int = 6
    window: float = 10800
    manual_cooldown: float = 60
    enforce: bool = False
    # Restart for a stuck suspend even in observe mode. The one problem whose cause is proven.
    restart_on_stuck_suspend: bool = False


@dataclass
class State:
    unhealthy_since: float | None = None
    grace_until: float = 0.0
    auto_restarts: list[float] = field(default_factory=list)
    manual_restarts: list[float] = field(default_factory=list)
    last_verdict: str = "starting"
    last_problems: list[str] = field(default_factory=list)


def problems_of(obs: Observation, cfg: Config) -> list[str] | None:
    """What is wrong with Steam. None = not in Game Mode (do nothing); [] = healthy."""
    if not obs.session_active:
        return None
    # A self-update legitimately removes the client and the web helper for a while. Tolerate it
    # for update_grace, then count it: an updater hung for fifteen minutes is itself the fault.
    if obs.updater_age is not None and obs.updater_age < cfg.update_grace:
        return []
    found = []
    if obs.steam_age is None:
        found.append("steam client not running")
    else:
        if not obs.webhelper:
            found.append("steamwebhelper not running")
        # Discovery opens some seconds after the client starts; judge it only once the client
        # has had startup_grace to get there.
        if not obs.listening and obs.steam_age >= cfg.startup_grace:
            found.append(f"Remote Play discovery ({DISCOVERY_PORT}/tcp) not listening")
        if obs.suspend_stuck:
            found.append(obs.suspend_stuck)
    return found


def acts(problems: list[str] | None, cfg: Config) -> bool:
    """Whether a `restart` verdict is carried out (True) or only logged (False)."""
    if cfg.enforce:
        return True
    return bool(
        cfg.restart_on_stuck_suspend
        and problems
        and all(p.startswith("Steam UI stuck mid-suspend") for p in problems)
    )


def decide(now: float, problems: list[str] | None, st: State, cfg: Config) -> str:
    """Return the verdict: idle | healthy | grace | waiting | rate_limited | restart."""
    if problems is None:
        st.unhealthy_since = None
        return "idle"
    if not problems:
        st.unhealthy_since = None
        return "healthy"
    if now < st.grace_until:
        return "grace"
    if st.unhealthy_since is None:
        st.unhealthy_since = now
    if now - st.unhealthy_since < cfg.unhealthy_for:
        return "waiting"
    st.auto_restarts = [t for t in st.auto_restarts if now - t < cfg.window]
    if len(st.auto_restarts) >= cfg.max_restarts:
        return "rate_limited"
    return "restart"


def manual_allowed(now: float, st: State, cfg: Config) -> bool:
    return not st.manual_restarts or now - st.manual_restarts[-1] >= cfg.manual_cooldown


def peer_allowed(peer: str, allow: set[str]) -> bool:
    # An IPv4 client reaching a dual-stack socket arrives as ::ffff:a.b.c.d.
    ip = peer[7:] if peer.startswith("::ffff:") else peer
    return ip in allow or ip in {"127.0.0.1", "::1"}


# --------------------------------------------------------------------------------------------
# ACTING
# --------------------------------------------------------------------------------------------


class Guard:
    def __init__(
        self, cfg: Config, unit: str, state_file: str, allow: set[str], steam_log: str = ""
    ):
        self.cfg, self.unit, self.state_file, self.allow = cfg, unit, state_file, allow
        self.steam_log = steam_log
        self.lock = threading.Lock()
        self.st = State(grace_until=time.time() + cfg.startup_grace)
        self.obs: Observation | None = None
        self._load()

    def _load(self) -> None:
        try:
            with open(self.state_file) as fh:
                saved = json.load(fh)
            self.st.auto_restarts = [float(t) for t in saved.get("auto_restarts", [])]
            self.st.manual_restarts = [float(t) for t in saved.get("manual_restarts", [])][-20:]
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(
                {
                    "auto_restarts": self.st.auto_restarts,
                    "manual_restarts": self.st.manual_restarts[-20:],
                },
                fh,
            )
        os.replace(tmp, self.state_file)

    def restart(self, why: str, manual: bool) -> bool:
        now = time.time()
        log(f"RESTART ({'manual' if manual else 'watchdog'}) {self.unit}: {why}")
        # --no-block: the session takes many seconds to come back, and this process must keep
        # answering /healthz meanwhile. The outcome is judged by the next observations.
        rc = subprocess.run(
            ["systemctl", "--user", "--no-block", "restart", self.unit], check=False
        ).returncode
        (self.st.manual_restarts if manual else self.st.auto_restarts).append(now)
        self.st.grace_until = now + self.cfg.startup_grace
        self.st.unhealthy_since = None
        self._save()
        if rc != 0:
            log(f"RESTART FAILED rc={rc}")
        return rc == 0

    def tick(self) -> None:
        obs = observe(self.unit, self.steam_log)
        now = time.time()
        with self.lock:
            self.obs = obs
            problems = problems_of(obs, self.cfg)
            verdict = decide(now, problems, self.st, self.cfg)
            # Log TRANSITIONS only, so a long outage or a rate-limited spell is one line, not one
            # per interval.
            if verdict != self.st.last_verdict or (problems or []) != self.st.last_problems:
                extra = (
                    f" — {len(self.st.auto_restarts)} automatic restarts in the last "
                    f"{self.cfg.window:.0f}s (max {self.cfg.max_restarts}); NOT restarting"
                    if verdict == "rate_limited"
                    else ""
                )
                log(
                    f"state {self.st.last_verdict} -> {verdict}: "
                    f"{'; '.join(problems or []) or 'ok'}{extra}"
                )
            self.st.last_verdict, self.st.last_problems = verdict, problems or []
            if verdict == "restart":
                if acts(problems, self.cfg):
                    self.restart("; ".join(problems or []), manual=False)
                else:
                    # OBSERVE MODE: report what would have happened and start a grace period so
                    # the log carries one line per would-be restart, not one per interval.
                    log(f"WOULD RESTART (observe mode): {'; '.join(problems or [])}")
                    self.st.grace_until = now + self.cfg.startup_grace
                    self.st.unhealthy_since = None

    def health(self) -> dict:
        now = time.time()
        with self.lock:
            o = self.obs
            return {
                "verdict": self.st.last_verdict,
                "problems": self.st.last_problems,
                "mode": "enforce" if self.cfg.enforce else "observe",
                "session_active": o.session_active if o else None,
                "steam_age_s": round(o.steam_age) if o and o.steam_age is not None else None,
                "updating": bool(o and o.updater_age is not None),
                "webhelper": o.webhelper if o else None,
                "remote_play_listening": o.listening if o else None,
                "suspend_stuck": o.suspend_stuck if o else None,
                "restart_on_stuck_suspend": self.cfg.restart_on_stuck_suspend,
                "auto_restarts_in_window": len(
                    [t for t in self.st.auto_restarts if now - t < self.cfg.window]
                ),
                "max_restarts": self.cfg.max_restarts,
                "window_s": self.cfg.window,
                "last_manual_restart_age_s": (
                    round(now - self.st.manual_restarts[-1]) if self.st.manual_restarts else None
                ),
            }


def log(msg: str) -> None:
    # stdout of a --user unit lands in the journal, where any log shipper can collect it.
    print(f"steam-guard: {msg}", flush=True)


def make_handler(guard: Guard):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _gate(self) -> bool:
            if peer_allowed(self.client_address[0], guard.allow):
                return True
            log(
                f"REFUSED {self.command} {self.path} from {self.client_address[0]} (not allowlisted)"
            )
            self._send(403, {"error": "not allowlisted", "peer": self.client_address[0]})
            return False

        def do_GET(self) -> None:  # noqa: N802 — http.server's naming
            if not self._gate():
                return
            if self.path == "/healthz":
                self._send(200, guard.health())
            else:
                self._send(404, {"error": "unknown path"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._gate():
                return
            if self.path != "/steam/restart":
                self._send(404, {"error": "unknown path"})
                return
            with guard.lock:
                if not manual_allowed(time.time(), guard.st, guard.cfg):
                    self._send(
                        429,
                        {
                            "error": "restarted moments ago; wait",
                            "cooldown_s": guard.cfg.manual_cooldown,
                        },
                    )
                    return
                ok = guard.restart(f"requested by {self.client_address[0]}", manual=True)
            self._send(202 if ok else 500, {"accepted": ok, "unit": guard.unit})

        def log_message(self, fmt: str, *args) -> None:  # silence per-request access logging
            return

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--unit", default="gamescope-session-plus@steam.service")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--allow", default="", help="comma-separated client IPs allowed to call")
    ap.add_argument("--state-file", required=True)
    ap.add_argument("--interval", type=float, default=Config.interval)
    ap.add_argument("--unhealthy-for", type=float, default=Config.unhealthy_for)
    ap.add_argument("--startup-grace", type=float, default=Config.startup_grace)
    ap.add_argument("--update-grace", type=float, default=Config.update_grace)
    ap.add_argument("--max-restarts", type=int, default=Config.max_restarts)
    ap.add_argument("--window", type=float, default=Config.window)
    ap.add_argument("--manual-cooldown", type=float, default=Config.manual_cooldown)
    ap.add_argument("--mode", choices=["observe", "enforce"], default="observe")
    ap.add_argument(
        "--steam-log",
        default=os.path.expanduser("~/.local/share/Steam/logs/webhelper_js.txt"),
        help="Steam UI log read for the stuck-suspend signature; empty disables the check",
    )
    ap.add_argument(
        "--restart-on-stuck-suspend",
        action="store_true",
        help="restart for a stuck suspend even in observe mode",
    )
    ap.add_argument("--once", action="store_true", help="observe once, print JSON, exit")
    a = ap.parse_args()

    cfg = Config(
        a.interval,
        a.unhealthy_for,
        a.startup_grace,
        a.update_grace,
        a.max_restarts,
        a.window,
        a.manual_cooldown,
        a.mode == "enforce",
        a.restart_on_stuck_suspend,
    )
    allow = {ip.strip() for ip in a.allow.split(",") if ip.strip()}
    guard = Guard(cfg, a.unit, a.state_file, allow, a.steam_log)

    if a.once:
        guard.tick()
        print(json.dumps(guard.health()))
        return 0

    server = ThreadingHTTPServer((a.bind, a.port), make_handler(guard))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(
        f"started: mode={a.mode} stuck_suspend_restart={cfg.restart_on_stuck_suspend} port={a.port} allow={sorted(allow)} max={cfg.max_restarts}/"
        f"{cfg.window:.0f}s unhealthy_for={cfg.unhealthy_for:.0f}s grace={cfg.startup_grace:.0f}s"
    )
    while True:
        try:
            guard.tick()
        except Exception as exc:  # a bad read must never kill the watchdog
            log(f"tick failed: {exc!r}")
        time.sleep(cfg.interval)


if __name__ == "__main__":
    sys.exit(main())
