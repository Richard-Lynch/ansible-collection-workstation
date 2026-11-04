# bazzite_workstation

Post-install setup for a Bazzite gaming workstation.

Written for an AMD desktop, including a full `bazzite` → `bazzite-deck` variant rebase into Game
Mode. Run `probe` first on any NEW machine — the default flatpak list is a starting point, not a
recommendation.

## The model

Bazzite is image-based (rpm-ostree): the base image is immutable. That changes where things go.

| Layer | Mechanism | Reboot? | Survives image rebase |
|---|---|---|---|
| GUI applications | **flatpak** | no | yes |
| CLI tools | **distrobox** | no | yes |
| User config | `~/.config` dotfiles | no | yes |
| Base image | `rpm-ostree` layering | **yes** | re-resolved |

**Layering is the last resort.** Every layered package slows `rpm-ostree upgrade`, must
re-resolve on each image rebase, can block an upgrade outright on conflict, and needs a reboot.
`bazzite_layer_packages` is empty by default and that is correct, not an oversight.

## Entrypoints

| `bazzite_action` | Does | Writes |
|---|---|---|
| `probe` | survey what the machine already has, incl. image-variant drift | a survey file (`bazzite_probe_output`, when `bazzite_probe_save`) |
| `status` | is an image update running, how far along, and how much is it pulling | nothing |
| `rebase` | converge the image **variant** declared in inventory | image, **needs reboot + confirm** |
| `sensors` | temperatures, clocks, power and fan RPM, with thresholds — run under load | nothing |
| `fan_report` | **why** the fans are at this speed: PWM duty + control mode per header | nothing |
| `fan_sweep` | hold each declared header at every duty: stall point + noise rating | PWM, temporarily |
| `image` | converge the variant, then update along it | image, **needs reboot** |
| `deck_daemons` | verify the image gated the Deck-hardware units; repair if not | systemd masks |
| `steam_guard` | watchdog that restarts a **dead** Game Mode Steam (max 6 per 3h), plus the allowlisted endpoint the Deck's "Restart Steam" tile calls; `observe` mode first | a `--user` unit, `$HOME` only |
| `steamos` | steamos-manager state (governor, GPU, CEC, login mode); converge HDMI-CEC | CEC settings |
| `autologin` | autologin, and the Game Mode session on a deck image | DM config |
| `flatpaks` | install the declared flatpak set | flatpaks |
| `gaming` | MangoHud + GameMode config | dotfiles |
| `layer` | rpm-ostree layered packages | image, **needs reboot** |
| `power_report` | did it sleep, which power stack is live, and is the config in effect? | nothing |
| `sleep_inhibit` | mask/unmask the systemd sleep targets so the machine cannot suspend | systemd masks |
| `fan_hold` | hold one header at one duty, with a detached deadman that restores automatic control | PWM, temporarily |
| `fan_curve` | program the Super-I/O's own fan curves, optionally with a boot unit that re-applies them | chip registers, a boot unit |
| `controllers` | every game controller the kernel and Steam can see | nothing |
| `controller_probe` | which physical button sends which event code (interactive) | nothing |
| `lighting` | OpenRGB SDK server and the reactive RGB daemon (user units) | `--user` units |
| `lighting_identify` | light each RGB header distinctly so headers can be mapped to hardware | LED colours, temporarily |
| `display_report` | what the machine can do with the display and TV over HDMI, CEC in particular | nothing |
| `session_report` | the Game Mode session's argv, env and journal, for a blank-screen fault | nothing |
| `sunshine` | Sunshine streaming: config, apps, autostart, compositor HDR | config, autostart |
| `wol` | enable Wake-on-LAN on the wired NIC, persistently | NIC/NM setting |
| `sudoers` | passwordless sudo for the declared user (bootstrap) | `/etc/sudoers.d` |
| `dhcp_renew` | re-acquire the DHCP leases so a new reservation takes effect now | lease |
| `reboot` | reboot and verify the settings that apply only at session start | reboot |
| `power_off` | power the machine off (needs `bazzite_power_off_confirm`) | **power off** |
| `hostname` | set the static hostname | hostname |
| `network` | stable network identity (permanent MAC, wired preferred; optionally no WiFi autoconnect) so a DHCP reservation holds | NM profiles |
| `power` | KDE powerdevil display/lock/suspend timeouts (Plasma session only) | `powerdevilrc` |
| `game_session` | Game Mode session overrides (output, xwayland count), compared against the live argv | `environment.d` file |
| `firmware_report` | fwupd devices and available updates | nothing |
| `all` | drift **check** + `hostname`/`network`/`power`/`sleep_inhibit`/`flatpaks`/`gaming` (+ `autologin` in Game Mode) | — |

`all` deliberately **excludes** `layer`: a reboot-requiring change with a permanent cost on
future updates should never happen as a side effect of "set the machine up".

> **The `bazzite_action=` interface is due to be replaced.** Selecting work with an extra-var puts
> play-level control flow inside the role and hides every entrypoint from `--list-tasks` and
> ansible-lint. The intended shape is one entrypoint per concern (`tasks_from`), so the caller's
> play names the work and extra-vars carry only `*_apply` / `*_confirm` gates.

## Two power stacks, and only one of them is KDE

`power` writes `~/.config/powerdevilrc`. That is meaningful **only when powerdevil is running** —
i.e. on a Plasma desktop session. On the **Game Mode image** (`bazzite-deck`) the session is
gamescope: there is no powerdevil, and those settings govern nothing while still reading back
exactly as written.

The failure this guards against: `AutoSuspendAction=0` (suspend disabled) on disk, no powerdevil
process, and the machine suspending anyway. `power` **detects this and refuses** rather than
reporting a green run that changes nothing; inside `all` it skips with an explanation instead, so
convergence still completes.

On the Game Mode image the two real suspend owners are:

| owner | reachable from Ansible? |
|---|---|
| Steam Game Mode idle timer | **No** — it lives in cloud-synced Steam user settings, not in `localconfig.vdf`, `registry.vdf` or `steam.cfg` |
| HDMI-CEC via `cecd` | Only where a CEC adapter exists — see below |

Because neither can be converged from a config file, **`sleep_inhibit` is the enforceable
answer**: it masks `sleep.target`, `suspend.target`, `hibernate.target`, `hybrid-sleep.target` and
`suspend-then-hibernate.target`, which is the one layer every suspend request passes through. It is
declarative in both directions (`bazzite_sleep_inhibit: false` unmasks), defaults to **off**, and
verifies against logind's own `CanSuspend` rather than trusting the unit files.

Set it per host in inventory — it is a fact about whether that machine may disappear, not
something a role can be right about for every caller.

### HDMI-CEC may be entirely inert

`steamosctl` stores and reports the CEC properties faithfully **whether or not any CEC hardware
exists**. On a desktop Radeon there is none — no `/dev/cec*`, no `/sys/class/cec/`, because amdgpu
registers no CEC adapter there — so all five settings, `suspend_device` included, are
recorded intent that nothing can ever act on. `steamos` now counts real adapters and says so, to
stop anyone believing the TV can suspend a machine it cannot reach.

### `fan_sweep` — measuring what no sensor reports

The fan policy needs a duty floor per header, and two of the numbers behind it cannot be read
from sysfs on many boards:

* **the stall point** — the duty below which a fan stops and will not restart without a kick.
  A board that declares no `pwm*_min_output` and no `fan*_min` gives nothing to read until swept.
* **the noise** — no sensor measures it. It needs ears.

Both are per-header: one header can sit at 28% duty for 600 RPM while another runs 3000 RPM, so a
single "25% is quiet" answer would be wrong for most headers.

The sweep takes the header to **manual mode**, so for its duration the hardware curve is not
protecting that fan. Three things follow, and all are load-bearing:

1. the sweep is **one process** (`files/fan_sweep.py`) with the restore in a `finally` plus
   SIGINT/SIGTERM handlers — Ansible cannot guarantee a restore *between* two tasks;
2. the task wraps it again in `block`/`always`, covering the case where the script is killed
   before installing its handlers;
3. the restore is confirmed by **read-back**, and a sweep whose restore cannot be confirmed
   **fails** — a fan left under no thermal control must never pass quietly.

Rating needs a TTY, which an Ansible run does not have, so the play measures RPM unattended and
prints the exact command to re-run on the box for the listening pass.

Which headers are swept is declared in inventory as `bazzite_fan_sweep_headers` — a list of
`{header, note, steps?}` — rather than passed per run, because what is plugged into each header
is a fact about the board, not the role. The note travels into the report and the result
filename, so a recorded sweep says what it was of.

```bash
ansible-playbook bazzite.yml -e bazzite_action=fan_sweep
ansible-playbook bazzite.yml -e bazzite_action=fan_sweep -e bazzite_fan_sweep_apply=true
```

**A header listed in `bazzite_fan_sweep_pump_headers` is refused outright.** The sweep searches
downward for a stall point; on a pump that risks cavitation and loss of coolant flow, and a
pump's RPM says nothing about whether coolant is moving.

## The base image is inventory config

Which ublue variant a machine runs is a fact about that machine, so it is **declared in
inventory** and has no role default:

```yaml
bazzite_image_variant: bazzite        # or bazzite-deck, bazzite-gnome, …
```

`bazzite_image_ref` and `bazzite_image_refspec` are **derived** from it (with
`bazzite_image_registry` and `bazzite_image_tag`), and the `ostree-image-signed:docker://`
transport is hardcoded — `ghcr.io/ublue-os` is sigstore-gated, and a bare `docker://` ref rebases
successfully with signature verification silently dropped.

Changing the variant rebases the machine, but **only** with `bazzite_apply=true` **and**
`bazzite_rebase_confirm=true`. Two flags, because `bazzite_apply` is the role's universal write
flag and replacing an operating system is a different category of act — a staged deployment
activates on the next reboot from *any* cause, so an unintended one surprises you later with no
play running.

Drift is reported by `probe`, `rebase`, `image` and `all`; `image` **fails** rather than updating
along a refspec the inventory no longer declares.

### `bazzite-deck` changes the display manager

The deck variant removes plasmalogin, installs SDDM, and ships `bazzite-autologin.service`, which
rewrites autologin on every boot and defaults the session to OpenGamepadUI. The `autologin`
entrypoint detects this and configures Game Mode the way the image expects — pinning
`zz-holo-autologin.conf` through the vendor's create-if-missing hook and clearing the
`/etc/bazzite/desktop_autologin` sentinel — rather than fighting it with a drop-in that every
in-UI "Return to Gaming Mode" would override.


## Usage

```bash
# 1. survey — read-only
ansible-playbook bazzite.yml -e bazzite_action=probe

# 2. dry run
ansible-playbook bazzite.yml -e bazzite_action=all

# 3. apply
ansible-playbook bazzite.yml -e bazzite_action=all -e bazzite_apply=true
```

Generate-don't-apply throughout: every entrypoint reports its plan and stops unless
`bazzite_apply=true`.

## Before trusting this

The probe exists because **Bazzite ships a great deal pre-configured** — Steam, Proton, MangoHud,
gamescope, GPU drivers, flatpak remotes. A setup play that reinstalls those is wasted work at
best and a conflict at worst.

Specific things to check against the probe output before a first apply:

- **The flatpak list.** Several defaults may already be present. Installing them is harmless but
  pointless; trim `bazzite_flatpaks` to the genuine gaps.
- **MangoHud's toggle keybind.** `Shift_R+F12` is Bazzite's documented default, but if the image
  ships its own config this role overwrites it.
- **GameMode's governor names.** `performance` / `schedutil` must exist on the running kernel.
- **Whether GameMode is even used.** Bazzite may apply its own scheduling; this config assumes
  desktop rather than handheld power behaviour.

## What it deliberately does not do

- Install Steam, Proton, MangoHud or gamescope — Bazzite ships them.
- Touch the base image unless `bazzite_layer_packages` is set explicitly.
- Configure dev tooling or monitoring agents. A dpkg-based agent install **will not work on an
  immutable host**; it needs a container variant.

## Notes

- `probe` parses `rpm-ostree status --json` defensively: `from_json` raises on empty input, so a
  missing or failing rpm-ostree would otherwise crash the report rather than be reported by it.
- `layer` checks **every** deployment for its read-back, not just the booted one — `--apply-live`
  leaves the package in the pending deployment, so checking `deployments[0]` alone can miss a
  successful layering.


## What the role does NOT manage: Steam and Remote Play

Steam's own settings are deliberately out of scope, and it is worth recording why so the question
is not reopened from scratch:

- **The Remote Play performance overlay is a CLIENT setting.** It is rendered by the Steam Link
  client, and the stats include streaming metrics only the client knows. The host's own overlay
  config (`MANGOHUD_CONFIGFILE`, written by Steam) reads `no_display`. Turn it off on the client:
  STEAM → Remote Play → performance overlay.
- **`steamosctl` has no streaming commands.** It covers hardware and power only — CPU governor
  and scheduler, GPU power profile and clocks, TDP, fan control, WiFi power management, HDMI-CEC,
  charge limits, and the default login mode. The `steamos` entrypoint reports all of it.
- **`localconfig.vdf` / `config.vdf` are a poor Ansible target.** Tens of KB of per-game state, and the `streaming` block holds Remote Play **pairing keys** — vendoring that into
  a repository would publish credentials. Steam also rewrites both files on exit.

What the role DOES control is the part that breaks in practice: the image variant, the
login mode and session, autologin, and the RGB units.
