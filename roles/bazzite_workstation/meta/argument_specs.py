# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

# Flatpak application IDs. GUI apps go here rather than into rpm-ostree layering: layered
# packages slow every future image update and must be re-resolved on each rebase, while flatpaks
# are independent of the image entirely.
#
# ASSUMPTION TO VERIFY ON THE REAL MACHINE: Bazzite ships a lot of this already, and installing
# what is present is wasted work rather than harmful. Run the `probe` entrypoint first and trim
# this list to the genuine gaps.
DEFAULT_FLATPAKS = [
    # --- gaming ---
    "io.github.benjamimgois.goverlay",  # MangoHud/vkBasalt configuration GUI
    "com.heroicgameslauncher.hgl",  # Epic/GOG/Amazon launcher
    # --- utility ---
    "io.missioncenter.MissionCenter",  # resource monitor that understands GPU
    # --- emulation ---
    # NO EmuDeck HERE. It is NOT on Flathub — "org.EmuDeck.EmuDeck" does not exist and an install
    # of it fails (verified: `flatpak search EmuDeck` returns no matches). EmuDeck ships as an
    # installer script that sets up RetroArch, the standalone emulators, the ROM tree and Steam
    # integration; on Bazzite the supported route is the Bazzite Portal, or running EmuDeck's
    # own installer. Neither is a flatpak, so neither belongs in this list.
    # --- hardware control ---
    # RGB control. ASUS's Armoury Crate is Windows-only, so this is the Linux answer.
    #
    # TWO CAVEATS, both worth knowing before relying on it:
    #   1. Support for very new hardware lags. A board or GPU newer than the installed OpenRGB release
    #      may not be detected at all. Installing costs nothing, but do not plan around it
    #      working until it has been confirmed on the machine.
    #   2. OpenRGB and firmware/AURA settings CONFLICT. Once OpenRGB drives a device it overwrites
    #      the firmware-set lighting and that state tends to persist across reboots — so
    #      "OpenRGB under Linux, AURA under Windows" is not a clean split. Pick one source of
    #      truth per device.
    #
    # Needs udev rules and i2c access for motherboard/GPU controllers; the flatpak prompts for
    # what it needs. If detection fails, the fallback is to set the lighting once in BIOS and
    # leave it — firmware lighting applies at boot regardless of OS.
    "org.openrgb.OpenRGB",
    # GPU fan/power curves and monitoring for AMD cards — the Linux counterpart to what the
    # firmware does for chassis fans. Useful on a discrete Radeon; harmless elsewhere.
    "io.github.ilya_zlobintsev.LACT",
]

# rpm-ostree LAYERED packages. Deliberately EMPTY by default.
#
# Layering is the last resort on an image-based system: each package slows `rpm-ostree upgrade`,
# has to resolve again on every image rebase, and can block an update outright on conflict. It
# also requires a REBOOT to take effect. Reach for flatpak or distrobox first; layer only what
# must exist in the base image (kernel modules, drivers, system services).
DEFAULT_LAYER_PACKAGES: list[str] = []


argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Post-install setup for a Bazzite gaming workstation",
            description=[
                "Configures a freshly-installed Bazzite box: flatpak applications, gaming",
                "tunables (MangoHud, GameMode), and optional rpm-ostree layered packages.",
                "Entrypoints are selected by bazzite_action; see the README for the full table.",
                "Prefers flatpak and distrobox over rpm-ostree layering, because layered",
                "packages slow image updates and must be re-resolved on every rebase.",
                "Reports what it would do and stops unless bazzite_apply=true.",
            ],
            version_added="1.1",
            author=DEFAULT_AUTHOR,
            options={
                "bazzite_action": OptionSpec(
                    type="str",
                    required=False,
                    default="probe",
                    choices=[
                        "probe",
                        "status",
                        "sensors",
                        "fan_report",
                        "fan_sweep",
                        "fan_hold",
                        "fan_curve",
                        "controllers",
                        "controller_probe",
                        "lighting",
                        "lighting_identify",
                        "display_report",
                        "session_report",
                        "sunshine",
                        "autologin",
                        "wol",
                        "sudoers",
                        "dhcp_renew",
                        "image",
                        "rebase",
                        "reboot",
                        "hostname",
                        "network",
                        "power",
                        "power_report",
                        "power_off",
                        "game_session",
                        "sleep_inhibit",
                        "deck_daemons",
                        "steam_guard",
                        "steamos",
                        "firmware_report",
                        "flatpaks",
                        "gaming",
                        "layer",
                        "all",
                    ],
                    description=[
                        "Which entrypoint main.yml dispatches to. Defaults to the read-only",
                        "probe, so a bare run against an unfamiliar machine changes nothing.",
                        "'all' runs the drift check plus hostname, network, power, sleep_inhibit,",
                        "flatpaks and gaming (and autologin in Game Mode), but NOT layer, which",
                        "needs a reboot.",
                    ],
                ),
                "bazzite_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Actually make changes. Default false reports the planned work and",
                        "stops, so a run against an unfamiliar machine is always safe.",
                    ],
                ),
                "bazzite_flatpaks": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=DEFAULT_FLATPAKS,
                    description=[
                        "Flatpak application IDs to install from Flathub.",
                        "Run the probe entrypoint first — Bazzite ships much of this already.",
                    ],
                ),
                "bazzite_openrgb_udev": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Install OpenRGB's udev rules. The Flatpak cannot do this itself, and",
                        "without them it detects devices but cannot control most of them.",
                    ],
                ),
                "bazzite_openrgb_udev_vendors": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[],
                    description=[
                        "USB vendor IDs whose USB and hidraw nodes the OpenRGB udev rules grant",
                        "to the logged-in seat (TAG+=uaccess), each a dict with `id` (four hex",
                        "digits) and an optional `note` printed beside it in the rules file.",
                        "EMPTY BY DEFAULT: which RGB hardware a machine has is inventory config.",
                        "The i2c rule (SMBus access for RAM and board zones) is written",
                        "regardless.",
                    ],
                ),
                "bazzite_layer_packages": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=DEFAULT_LAYER_PACKAGES,
                    description=[
                        "Packages to layer with rpm-ostree. EMPTY by default and deliberately",
                        "so: layering slows updates, re-resolves on every rebase, can block an",
                        "upgrade on conflict, and needs a reboot. Use flatpak or distrobox",
                        "unless the thing must live in the base image.",
                    ],
                ),
                "bazzite_sudo_from_1password": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Read the become password from 1Password for the sudoers bootstrap,",
                        "rather than requiring --ask-become-pass.",
                        "Solves the chicken-and-egg of needing sudo to enable passwordless sudo,",
                        "without a human at a prompt. Off by default because where a host's",
                        "password lives is inventory config; set true together with",
                        "bazzite_sudo_secret_item and bazzite_sudo_secret_vault.",
                    ],
                ),
                "bazzite_sudo_secret_item": OptionSpec(
                    type="str",
                    # No default: which secret holds a host's password is inventory config.
                    required=False,
                    description=[
                        "1Password item holding this host's sudo password.",
                        "Required when bazzite_sudo_from_1password is true.",
                    ],
                ),
                "bazzite_sudo_secret_vault": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "1Password vault the sudo password item lives in.",
                        "Required when bazzite_sudo_from_1password is true.",
                    ],
                ),
                "bazzite_sudo_user": OptionSpec(
                    # No default: whose sudo this grants is inventory config. A default here would
                    # silently target the wrong account on any other machine. Not required at the
                    # spec level: only the sudoers entrypoint uses it, and it asserts it there.
                    type="str",
                    required=False,
                    description="User granted passwordless sudo by the sudoers entrypoint.",
                ),
                "bazzite_sudoers_file": OptionSpec(
                    type="str",
                    required=False,
                    default="bazzite-ansible",
                    description=[
                        "Filename under /etc/sudoers.d. Named so its purpose is obvious to",
                        "whoever finds it later; delete the file to revert.",
                    ],
                ),
                "bazzite_sensors_load_modules": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Attempt to load the Super-I/O sensor modules so motherboard fan headers",
                        "and board temperatures become readable.",
                        "Not autoloaded by the kernel because blind Super-I/O probing can",
                        "conflict with ACPI; safe and reversible with `modprobe -r`.",
                    ],
                ),
                "bazzite_sensor_modules": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=["nct6775", "asus-ec-sensors"],
                    description=[
                        "Modules to try, in order. nct6775 covers most ASUS Super-I/O chips;",
                        "asus-ec-sensors covers newer boards that read via the embedded",
                        "controller. A module that does not match simply registers nothing.",
                    ],
                ),
                "bazzite_status_sample_seconds": OptionSpec(
                    type="int",
                    required=False,
                    default=10,
                    description=[
                        "Seconds between the two repo-size samples the status entrypoint takes.",
                        "Two readings distinguish 'downloading' from 'hung'; one cannot.",
                    ],
                ),
                # bazzite_image_ref is DERIVED, not declared — see tasks/setup_vars.yml. It used
                # to be a single hand-set string, but that conflates two different things: the
                # image this machine SHOULD run (an inventory decision) and the reference the digest
                # comparison comes from. Pointing one var at a new variant made the comparison
                # cross-variant — unrelated digests, so a permanent, false "UPDATE AVAILABLE" —
                # before any rebase had happened.
                "bazzite_image_registry": OptionSpec(
                    type="str",
                    required=False,
                    default="ghcr.io/ublue-os",
                    description=[
                        "Registry and namespace the base image is pulled from.",
                        "A role default because it is right for ANY Universal Blue caller; the",
                        "VARIANT is a per-machine decision and belongs in inventory.",
                    ],
                ),
                "bazzite_image_variant": OptionSpec(
                    # No default, deliberately. Which variant a machine runs is a fact
                    # about that machine, exactly like its hostname, so it lives in inventory.
                    # A default of 'bazzite' would make the role silently right for the desktop
                    # build and silently wrong for a deck or gnome one.
                    type="str",
                    required=True,
                    description=[
                        "Universal Blue image variant this machine runs, e.g. 'bazzite' (KDE",
                        "desktop), 'bazzite-deck' (adds the gamescope Game Mode session and",
                        "SWAPS THE DISPLAY MANAGER from plasmalogin to SDDM), 'bazzite-gnome'.",
                        "Changing this REBASES the machine on the next image/rebase run — but",
                        "only with bazzite_apply=true AND bazzite_rebase_confirm=true.",
                    ],
                ),
                "bazzite_image_tag": OptionSpec(
                    type="str",
                    required=False,
                    default="stable",
                    description=[
                        "Image tag to track. 'stable' is the tested channel; 'latest' tracks the",
                        "rolling build and 'testing' the pre-release one.",
                    ],
                ),
                "bazzite_rebase_confirm": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Permit an image VARIANT rebase. Separate from bazzite_apply on purpose:",
                        "bazzite_apply is the role's universal write flag ('write dotfiles,",
                        "install flatpaks'), while a rebase replaces the operating system and,",
                        "for the deck variant, the display manager with it. A staged deployment",
                        "activates on the NEXT REBOOT FROM ANY CAUSE — a power cut included — so",
                        "an unintended one surprises you later with no play running.",
                    ],
                ),
                "bazzite_rebase_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=3600,
                    description=[
                        "Seconds allowed for the rebase pull. A variant switch is a near-full",
                        "image download, not an incremental delta.",
                    ],
                ),
                "bazzite_rebase_min_free_gb": OptionSpec(
                    type="int",
                    required=False,
                    default=20,
                    description=[
                        "Free space required under /sysroot before a rebase is attempted.",
                        "An ostree pull that runs out of space leaves a half-written repo and a",
                        "machine that still boots but cannot update.",
                    ],
                ),
                "bazzite_image_auto": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Enable the automatic image/flatpak update timer.",
                        "On by default: image updates are atomic and roll back with",
                        "`rpm-ostree rollback`, so unattended updating is far safer here than on",
                        "a package-based system — and a box with no timer never updates at all.",
                    ],
                ),
                "bazzite_image_auto_unit": OptionSpec(
                    type="str",
                    required=False,
                    default="uupd.timer",
                    description=[
                        "The automatic update timer. uupd is Bazzite's current updater and",
                        "covers image, flatpaks, distrobox and brew; ublue-update was its",
                        "predecessor. The play reports the unit's real state rather than",
                        "trusting the enable call, since the name varies across versions.",
                    ],
                ),
                "bazzite_image_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=3600,
                    description="Seconds to allow for the image pull. These are multi-GB downloads.",
                ),
                "bazzite_wired_priority": OptionSpec(
                    type="int",
                    required=False,
                    default=100,
                    description=[
                        "connection.autoconnect-priority for wired profiles. Higher wins, so a",
                        "value above the WiFi default (0) makes ethernet preferred when both",
                        "links are present — otherwise NetworkManager keeps whichever came up",
                        "first, which can leave the machine on WiFi with a cable attached.",
                    ],
                ),
                "bazzite_reboot_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=900,
                    description=[
                        "Seconds to wait for the machine to return. Generous because a first",
                        "boot into a new image is slower than a normal restart.",
                    ],
                ),
                "bazzite_gamescope_output": OptionSpec(
                    type="str",
                    required=False,
                    default="*,eDP-1",
                    description=[
                        "Which output Game Mode drives (gamescope --prefer-output). The DEFAULT",
                        "IS THE IMAGE'S OWN, kept so the role is correct for a Steam Deck too —",
                        "`*` then a laptop internal panel. On a desktop that is wrong and works",
                        "only because the wildcard happens to match the one connected output",
                        "first, which is order-dependent the moment a second display appears.",
                        "Declare the real connector in inventory (e.g. HDMI-A-1); the entrypoint",
                        "asserts it is actually connected before writing it.",
                    ],
                ),
                "bazzite_gamescope_xwayland_count": OptionSpec(
                    type="int",
                    required=False,
                    default=2,
                    description=[
                        "How many xwayland servers Game Mode runs (--xwayland-count). The image",
                        "default of 2 provides the nested server Steam Remote Play renders into,",
                        "and that server can cause a recurring black screen:",
                        "gamescope switches to presenting it when a client connects and never",
                        "switches back on disconnect, holding input devices that no longer",
                        "exist. Audio fine, overlay drawing, no image, Remote Play launches",
                        "going nowhere, and only a restart clears it because nothing crashes.",
                        "DO NOT SET 1: Steam launches every game on",
                        "DISPLAY=:1 (Bazzite exports STEAM_MULTIPLE_XWAYLANDS=1, and exporting 0",
                        "does not change it), so with one server no game can open a window.",
                        "A fix for the black screen must keep :1 alive.",
                    ],
                ),
                "bazzite_power_off_confirm": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Gate on the power_off entrypoint. DELIBERATELY NOT bazzite_apply:",
                        "that flag is passed routinely while converging a machine (`all` sets",
                        "it), and powering a streaming host off must never be",
                        "reachable as a side effect. Nothing in this role can power the machine",
                        "back on except a Wake-on-LAN magic packet, so a failed wake means",
                        "walking to the machine.",
                    ],
                ),
                "bazzite_power_off_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=180,
                    description=[
                        "Seconds to wait for the machine to STOP answering on port 22, which",
                        "is what proves it actually went down. `systemctl poweroff` returning",
                        "0 means the request was accepted, not that the shutdown completed —",
                        "a hung unit can keep the machine up, and a wake test against a machine",
                        "that never powered off reports a false success.",
                    ],
                ),
                "bazzite_hostname": OptionSpec(
                    # No default: a role must not decide what a machine is called. Asserted by the
                    # hostname entrypoint, the only one that uses it.
                    type="str",
                    required=False,
                    description=[
                        "Static hostname. The installer leaves this EMPTY, so the machine sends no",
                        "hostname to DHCP and the server may invent one from the IP address — the machine",
                        "ends up named after its own lease.",
                    ],
                ),
                "bazzite_power_display_minutes": OptionSpec(
                    type="int",
                    required=False,
                    default=60,
                    description=[
                        "Minutes of idle before the DISPLAY switches off.",
                        "KDE's default of a few minutes blanks the screen during cut-scenes and",
                        "films, because neither generates input events.",
                    ],
                ),
                "bazzite_power_lock_minutes": OptionSpec(
                    type="int",
                    required=False,
                    default=0,
                    description=[
                        "Minutes before the screen locks; 0 disables locking entirely.",
                        "Off by default for a home gaming box — a lock screen between you and a",
                        "paused game is friction with no threat model behind it.",
                    ],
                ),
                "bazzite_power_suspend_minutes": OptionSpec(
                    type="int",
                    required=False,
                    default=0,
                    description=[
                        "Minutes before the machine suspends; 0 disables suspend.",
                        "Separate from the display timeout: 'screen off' and 'machine asleep'",
                        "are different decisions, and suspend interrupts downloads and streaming.",
                    ],
                ),
                "bazzite_sleep_inhibit": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Mask the systemd sleep targets so the machine CANNOT suspend, whatever",
                        "asks. This is the only enforceable answer on the Game Mode",
                        "(bazzite-deck) image, where powerdevil does not run and the",
                        "bazzite_power_* settings govern nothing. Masking catches EVERY",
                        "requester at the one layer they all pass through.",
                        "CAUTION: Steam's UI PREPARES for a suspend before",
                        "asking logind, so a refused suspend leaves its main page BLACK until",
                        "Steam restarts. With this on, also set",
                        "bazzite_steam_idle_suspend_ac_seconds: 0 (Steam's own idle sleep off) and",
                        "bazzite_steam_guard_restart_on_stuck_suspend: true (recovery for a manual",
                        "Sleep press).",
                        "Fully reversible: set false to unmask. Off by default because a machine",
                        "that can never sleep is a real power cost and the wrong default for a",
                        "desktop — it is opt-in per host in inventory.",
                        "NOTE this blocks hibernate and suspend-then-hibernate too, by design.",
                    ],
                ),
                "bazzite_gamemode": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description="Write a GameMode configuration tuned for a desktop (not handheld).",
                ),
                "bazzite_mangohud_config": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description="Write a MangoHud config: a readable default overlay, toggled with R_SHIFT+F12.",
                ),
                "bazzite_probe_output": OptionSpec(
                    type="str",
                    required=False,
                    default="~/.local/state/iaac-bazzite-probe.json",
                    description="Where the probe entrypoint records its survey, for later comparison.",
                ),
                "bazzite_python": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/bin/python3",
                    description=[
                        "Interpreter used to run this role's helper scripts on the target.",
                        "Pinned to an absolute path rather than resolved from PATH: a path built",
                        "from $VIRTUAL_ENV or found via `command -v` is a classic works-here-",
                        "fails-in-CI dependency.",
                    ],
                ),
                "bazzite_rgb_color": OptionSpec(
                    type="str",
                    required=False,
                    default="FF6600",
                    description=[
                        "Colour to set, as six hex digits with NO leading '#'.",
                        "Only used when bazzite_apply=true; the lighting entrypoint reports",
                        "without writing otherwise.",
                    ],
                ),
                "bazzite_rgb_brightness": OptionSpec(
                    type="int",
                    required=False,
                    default=100,
                    description=[
                        "Brightness percentage (0-100) for devices whose mode supports it.",
                        "Silently ignored by devices that do not.",
                    ],
                ),
                "bazzite_rgb_mode": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "An ANIMATED effect to run instead of a static colour, e.g.",
                        "'Rainbow Wave' or 'Spectrum Cycle'. Empty (the default) means set a",
                        "static colour from bazzite_rgb_color instead.",
                        "Effect names are per-vendor and case-sensitive — run the lighting",
                        "entrypoint read-only to see what each device declares. A device that",
                        "does not offer the named effect is skipped, not failed.",
                    ],
                ),
                "bazzite_sunshine_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Whether Sunshine should be RUNNING. False converges the sunshine",
                        "entrypoint to stopped with no autostart entry, keeping the flatpak,",
                        "its config and its pairings so re-enabling is a flag flip.",
                        "The compositor-HDR half of that entrypoint converges either way.",
                    ],
                ),
                "bazzite_sunshine_restart": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Force a clean restart of Sunshine even when no config changed.",
                        "Needed after the process has been started more than once: the extra",
                        "instances cannot bind port 48010 and run on without a virtual gamepad,",
                        "so the stream works and the controller does not.",
                    ],
                ),
                "bazzite_sunshine_manage_config": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Template sunshine.conf and apps.json from this role.",
                        "Sunshine rewrites both files when settings change in its web UI, so",
                        "the repo and the browser are mutually exclusive sources of truth —",
                        "this makes it the repo. Set false to hand the files back to the UI.",
                    ],
                ),
                "bazzite_sunshine_apps": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[{"name": "Desktop", "image": "desktop.png"}],
                    description=[
                        "Apps offered to Moonlight clients. Keys: name, cmd, image, and the",
                        "optional auto_detach / wait_all / exit_timeout / elevated.",
                        "A `cmd` must go through `flatpak-spawn --host` — Sunshine is a flatpak",
                        "and an unprefixed command runs inside the sandbox where Steam does not",
                        "exist. Prefix with `setsid` so Sunshine does not read the launcher's",
                        "immediate return as the app exiting.",
                    ],
                ),
                "bazzite_sunshine_covers_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="{{ ansible_env.HOME }}/.var/app/dev.lizardbyte.app.Sunshine/config/sunshine/covers",
                    description="Where Sunshine keeps cover art.",
                ),
                "bazzite_sunshine_covers_helper": OptionSpec(
                    type="str",
                    required=False,
                    default="{{ ansible_env.HOME }}/.local/bin/iaac-sunshine-covers",
                    description="Where the cover-art resolver is installed on the target.",
                ),
                "bazzite_sunshine_adapter": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "Render node used for hardware encoding — the DISCRETE card, e.g.",
                        "/dev/dri/renderD128. Empty (the default) writes no adapter_name and",
                        "leaves the choice to Sunshine. Verify a declared node from",
                        "mem_info_vram_total, not from the number: with an integrated GPU",
                        "present the numbering does not reliably put the discrete card first.",
                    ],
                ),
                "bazzite_sunshine_hevc": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Offer HEVC. Roughly 30-40% better quality per bit than H.264 and",
                        "hardware-decoded by any remotely modern client, including the Deck.",
                        "Whether the 10-bit (HDR) profile is advertised alongside Main is",
                        "decided by bazzite_sunshine_hdr, not here.",
                    ],
                ),
                "bazzite_sunshine_hdr": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Advertise the 10-bit HDR profiles to clients (hevc_mode 3 / av1_mode 3",
                        "rather than 2, which is Main/8-bit only).",
                        "ON LINUX THIS IS ONLY HALF OF HDR. The dd_hdr_option settings that",
                        "switch the display into HDR for a stream are Windows-only, so the host",
                        "compositor must already be in HDR mode — otherwise the stream carries",
                        "an SDR image inside an HDR container and looks washed out.",
                        "Default OFF because that compositor state cannot be assumed, and a",
                        "client advertising HDR against an SDR host is worse than neither.",
                    ],
                ),
                "bazzite_sunshine_av1": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Offer AV1. RDNA 4 encodes it, but decode support is thinner —",
                        "the Steam Deck's RDNA2 has no AV1 decoder, so it would negotiate down",
                        "to HEVC anyway. Off until a client that benefits actually exists.",
                    ],
                ),
                "bazzite_sunshine_resolution_match": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Advertise client-matched resolutions so the host can drop from 4K to",
                        "the client's own size for the duration of a stream.",
                        "A 3840x2160 desktop streaming to a 1280x800 handheld encodes 8.1x the",
                        "pixels every frame for a screen that cannot show them.",
                    ],
                ),
                "bazzite_sunshine_resolutions": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=["1280x800", "1920x1080", "2560x1440", "3840x2160"],
                    description=[
                        "Resolutions advertised to clients. 1280x800 is the Steam Deck's native",
                        "panel; the rest cover a phone, a laptop and the host's own display.",
                    ],
                ),
                "bazzite_sunshine_fps": OptionSpec(
                    type="list",
                    elements="int",
                    required=False,
                    default=[30, 60, 90, 120],
                    description="Frame rates advertised to clients. The Deck's panel does 90.",
                ),
                "bazzite_sunshine_max_bitrate": OptionSpec(
                    type="int",
                    required=False,
                    default=0,
                    description=[
                        "Cap on the client-requested bitrate, in Kbps. 0 = uncapped.",
                        "Uncapped by default: on a wired host the real constraint is the",
                        "client's own link, and the client negotiates that.",
                    ],
                ),
                "bazzite_sunshine_qp": OptionSpec(
                    type="int",
                    required=False,
                    default=28,
                    description=[
                        "Quantisation parameter — LOWER is better quality and more bits.",
                        "28 is Sunshine's default and a sane balance; a dedicated encoder has",
                        "headroom to go lower if the link can carry it.",
                    ],
                ),
                "bazzite_sunshine_gamepad": OptionSpec(
                    type="str",
                    required=False,
                    default="x360",
                    description=[
                        "Virtual gamepad type. x360 is handled by every Proton title and by",
                        "Steam Input without a per-game mapping; ds4/switch need one.",
                    ],
                ),
                "bazzite_sunshine_log_level": OptionSpec(
                    type="int",
                    required=False,
                    default=2,
                    description=[
                        "0=verbose .. 5=none. 2 (info) diagnoses a failed stream without the",
                        "log growing unbounded, as it does at the default.",
                    ],
                ),
                "bazzite_sunshine_extra_origins": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=[],
                    description=[
                        "Additional origins allowed to reach the Sunshine web UI, as full",
                        "scheme://host:port values. The inventory name, ansible_host, the",
                        "primary IP and localhost are always included; this is for anything",
                        "else, such as a reverse proxy or an alternate DNS name.",
                    ],
                ),
                "bazzite_disable_wifi": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Stop WiFi autoconnecting on a machine that has working ethernet.",
                        "A dual-homed desktop holds an address on BOTH VLANs, and anything on",
                        "the WiFi subnet is then reached over the wireless route regardless of",
                        "default-route metrics — a handheld streaming from such a desktop goes",
                        "WiFi->AP->WiFi while a 5ms wired path sits idle.",
                        "Off by default: correct for a stationary desktop, wrong for a laptop.",
                        "The profile is kept, so re-enabling is one nmcli call.",
                    ],
                ),
                "bazzite_autologin_user": OptionSpec(
                    type="str",
                    # No default: which account a machine logs in as is inventory config.
                    required=False,
                    description=[
                        "User logged in automatically at boot. Required by the autologin",
                        "entrypoint.",
                        "Bazzite ships autologin pointed at 'plasma-setup', its first-run wizard",
                        "account — a leftover from installation that leaves the real user at the",
                        "greeter, with Steam and Sunshine unable to start.",
                    ],
                ),
                "bazzite_autologin_session": OptionSpec(
                    type="str",
                    required=False,
                    default="plasma",
                    description=[
                        "Session to start, matching a .desktop name in",
                        "/usr/share/wayland-sessions. A name that does not resolve fails SILENTLY",
                        "and leaves the greeter up, so the entrypoint asserts it exists first.",
                    ],
                ),
                "bazzite_autologin_relogin": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Log back in automatically after a logout, not only at boot.",
                        "Without it a logout leaves the machine at the greeter and silently",
                        "unavailable for streaming until someone is physically present.",
                    ],
                ),
                "bazzite_login_mode": OptionSpec(
                    type="str",
                    required=False,
                    default="desktop",
                    choices=["desktop", "game"],
                    description=[
                        "Which session the machine autologs into on a DECK-variant image.",
                        "'game'    -> gamescope Game Mode: /etc/bazzite/desktop_autologin is",
                        "             ABSENT and zz-holo-autologin.conf pins the session below.",
                        "'desktop' -> the sentinel file is present; Plasma as normal.",
                        "Ignored on non-deck variants, which ship no gamescope session.",
                        "On a deck image this also pulls autologin into the 'all' action: a",
                        "machine declaring Game Mode exists to boot unattended into a session.",
                    ],
                ),
                "bazzite_game_session": OptionSpec(
                    type="str",
                    required=False,
                    default="gamescope-session-ogui-steam.desktop",
                    choices=[
                        "gamescope-session-steam.desktop",
                        "gamescope-session-ogui-steam.desktop",
                    ],
                    description=[
                        "The Game Mode session .desktop, written into zz-holo-autologin.conf.",
                        "'gamescope-session-steam' is plain Steam Big Picture.",
                        "'gamescope-session-ogui-steam' is OpenGamepadUI ('Big Picture Plus')",
                        "and is THE IMAGE'S OWN DEFAULT, so it is the role default too: a role",
                        "default should not override the image without a reason.",
                    ],
                ),
                "bazzite_autologin_cleanup_stale": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Remove this role's autologin drop-in belonging to the OTHER display",
                        "manager. Off by default and deliberately: after a deck rebase the",
                        "plasmalogin drop-in is dead config, but it is ALSO what makes autologin",
                        "work on the rollback path — deleting it at cutover would land a",
                        "rollback at a greeter. Turn on once the rollback window has closed.",
                    ],
                ),
                "bazzite_deck_hw_units": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=[
                        "jupiter-fan-control",
                        "jupiter-dock-updater",
                        "vpower",
                        "sdgyrodsu",
                        "steamdeck-dsp",
                        "galileo-mura",
                    ],
                    description=[
                        "Deck-HARDWARE-only units the deck image ships unconditionally. On a",
                        "desktop board these start and fail (jupiter-fan-control aborts with",
                        "'DMI_ID Board Name not implemented!'), leaving permanently-failed units",
                        "that pollute every future `systemctl --failed` check.",
                        "Masked by the deck_daemons entrypoint. NOT a list of things to disable",
                        "for performance — these are inert-or-broken here either way; a crashed",
                        "fan daemon controls no fans, the BIOS curve does.",
                        "Deliberately EXCLUDES inputplumber/powerstation, which are",
                        "hardware-agnostic and expected to run — see bazzite_deck_generic_units.",
                    ],
                ),
                "bazzite_deck_generic_units": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=["inputplumber", "powerstation"],
                    description=[
                        "Deck-image units that are deliberately hardware-agnostic and SHOULD be",
                        "running: inputplumber (input remapping) and powerstation (DBus TDP/GPU",
                        "power control, what makes the Quick Access sliders work).",
                        "Asserted healthy rather than masked — the opposite expectation from",
                        "bazzite_deck_hw_units, which is why they are two separate lists.",
                    ],
                ),
                # HDMI-CEC, via steamos-manager (`steamosctl`). Only present on a deck-variant
                # image; the steamos entrypoint no-ops without it.
                #
                # WHY THESE ARE INVENTORY CONFIG: whether a TV may power the PC off, and whether
                # the PC may power the TV on, is a fact about one particular room — not something a
                # role can be right about for every caller. The defaults below are what the image
                # ships, so declaring nothing changes nothing.
                "bazzite_cec_manage": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Let the role converge the HDMI-CEC settings below. Off by default:",
                        "CEC decides whether a TV can suspend the machine, and a host that",
                        "vanishes mid-stream because someone turned the telly off is a",
                        "surprising thing to switch on without being asked.",
                    ],
                ),
                "bazzite_cec_control": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Accept TV remote-control passthrough over HDMI-CEC, so the telly's own",
                        "remote can drive Game Mode.",
                    ],
                ),
                "bazzite_cec_suspend_tv": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description="Turn the TV off when the machine suspends.",
                ),
                "bazzite_cec_suspend_device": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Suspend the machine when the TV is turned off.",
                        "CONSIDER FALSE ON A STREAMING HOST: with this on, switching the telly",
                        "off suspends the machine — which also ends any Remote Play session running",
                        "from another room, with nothing to explain why.",
                    ],
                ),
                "bazzite_cec_wake_tv": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description="Turn the TV on when the machine wakes.",
                ),
                "bazzite_cec_wake_device": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Wake the machine when the TV is turned on.",
                        "NOT SUPPORTED ON A DESKTOP RADEON and false by default: amdgpu links",
                        "the cec module but registers NO CEC adapter on a desktop Radeon — no",
                        "/dev/cec*, no /sys/class/cec, no CEC lines in the kernel log — so there",
                        "is no adapter to receive the wake. `hdmi-cec-wake-device-supported`",
                        "reports false and the entrypoint asserts before setting it true, rather",
                        "than writing a value that silently does nothing.",
                        "Wake-on-LAN is the working alternative (see the wol entrypoint).",
                    ],
                ),
                "bazzite_rgb_identify_path": OptionSpec(
                    type="str",
                    required=False,
                    default="{{ ansible_env.HOME }}/.local/bin/iaac-openrgb-identify",
                    description="Where the header-identification helper is installed.",
                ),
                "bazzite_fan_sweep_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Gate for the fan_sweep entrypoint. Sweeping takes a header to MANUAL",
                        "mode, so it is a write and reports-then-stops without this.",
                    ],
                ),
                "bazzite_fan_sweep_chip": OptionSpec(
                    # No default: which Super-I/O chip a board carries is inventory config.
                    type="str",
                    required=False,
                    description=[
                        "hwmon chip name carrying the fan headers (e.g. nct6799). Required by",
                        "the fan_sweep, fan_hold and fan_curve entrypoints. Located by NAME every run:",
                        "hwmonN numbering is not stable across reboots, so a remembered index",
                        "would read a different chip and read it plausibly rather than failing.",
                    ],
                ),
                "bazzite_fan_sweep_headers": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[],
                    description=[
                        "Headers to sweep, in order, each a dict with `header` (the pwm channel",
                        "index) and `note` (what it is and why it is worth sweeping — printed",
                        "in the report so a result is self-describing).",
                        "Optional per-entry `steps` overrides the shared duty list, because a",
                        "header that stalls high needs a different range from one that does not.",
                        "EMPTY BY DEFAULT: which headers exist and what is plugged into them is",
                        "inventory config, and a role that guessed would sweep a pump on some",
                        "other board.",
                    ],
                ),
                "bazzite_fan_sweep_steps": OptionSpec(
                    type="str",
                    required=False,
                    default="20,25,30,40,50,60,75,100",
                    description=[
                        "Duty percentages to hold, in order. Starts at 20 rather than 0 because",
                        "the interesting range is around the stall point; extend downward once",
                        "a sweep shows where that is for a given header.",
                    ],
                ),
                "bazzite_fan_sweep_settle": OptionSpec(
                    type="float",
                    required=False,
                    default=6.0,
                    description=[
                        "Seconds to hold each duty BEFORE measuring. A fan coasts rather than",
                        "stopping instantly, so measuring too early reports the coast, not the",
                        "steady state — which reads a stalled fan as healthy.",
                    ],
                ),
                "bazzite_fan_sweep_samples": OptionSpec(
                    type="int",
                    required=False,
                    default=5,
                    description=[
                        "Tacho reads averaged per step. The spread across them is the tell for",
                        "a fan that is hunting or on the edge of stalling.",
                    ],
                ),
                "bazzite_fan_hold_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description="Gate for the fan_hold entrypoint. Holding a header is a write.",
                ),
                "bazzite_fan_hold_release": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "End a hold session: return the header to automatic control and disarm",
                        "the deadman. Always finish a conversational sweep with this.",
                    ],
                ),
                "bazzite_fan_hold_header": OptionSpec(
                    type="int",
                    required=False,
                    default=1,
                    description=[
                        "Which pwm channel to hold. Set in the play or inventory rather than on",
                        "the command line — which header is which fan is inventory config.",
                    ],
                ),
                "bazzite_fan_hold_percent": OptionSpec(
                    type="int",
                    required=False,
                    default=50,
                    description=[
                        "Duty percent for THIS step. The conversational sweep changes it per",
                        "run; the default is a safe mid-range value rather than a low one, so a",
                        "mistaken bare run cannot stall a fan.",
                    ],
                ),
                "bazzite_fan_hold_deadman": OptionSpec(
                    type="int",
                    required=False,
                    default=600,
                    description=[
                        "Seconds before a DETACHED systemd timer returns the header to",
                        "automatic control on its own. Generous by design: between two steps no",
                        "process of ours is alive holding the header, so this must outlast a",
                        "human thinking about an answer. Every step re-arms it.",
                    ],
                ),
                "bazzite_fan_curve_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description="Gate for fan_curve. Reprogramming the chip's curve is a write.",
                ),
                "bazzite_fan_curves": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[],
                    description=[
                        "Curves to program into the Super-I/O, one dict per header:",
                        "`header`, `note`, and `points` (five {temp, pwm} pairs, ascending).",
                        "EMPTY BY DEFAULT and never given a role default: a curve encodes a",
                        "specific case, specific fans and a specific person's measured noise",
                        "tolerance. None of that generalises, and a default would be wrong on",
                        "every other machine while looking authoritative.",
                    ],
                ),
                "bazzite_fan_curve_persist": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Install a boot unit that reprograms the curves. The auto_point",
                        "registers are volatile, so without it a reboot restores the factory",
                        "curve — and these curves are the fan daemon's FALLBACK, which must not",
                        "silently revert to 'loud' every time the machine restarts.",
                    ],
                ),
                "bazzite_fan_curve_wait_seconds": OptionSpec(
                    type="int",
                    required=False,
                    default=30,
                    description=[
                        "How long the boot script waits for the Super-I/O chip to appear.",
                        "systemd-modules-load completing means modprobe returned, not that the",
                        "hwmon device has registered — a race that otherwise breaks boot",
                        "persistence.",
                    ],
                ),
                "bazzite_fan_curve_script": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/local/bin/iaac-fan-curve-restore",
                    description="Where the boot-time curve program is installed.",
                ),
                "bazzite_fan_curve_unit": OptionSpec(
                    type="str",
                    required=False,
                    default="fan-curve-restore.service",
                    description="Name of the boot unit.",
                ),
                "bazzite_fan_curve_unit_before": OptionSpec(
                    type="str",
                    required=False,
                    default="fand.service",
                    description=[
                        "Unit this must run BEFORE. The curve program has to land before the",
                        "fan daemon takes the headers, or the daemon's writes would be",
                        "overwritten by a later curve program.",
                    ],
                ),
                "bazzite_controller_probe_device": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "An event node to probe INSTEAD of the first gamepad found, e.g.",
                        "'event5'. Empty means the first. Useful when Steam is running and there",
                        "are two nodes for one pad — the physical device and the virtual",
                        "`Microsoft X-Box 360 pad` Steam Input synthesises — and you want one",
                        "specifically. The per-node comparison watches ALL of them regardless, so",
                        "this is for isolating a single node rather than for the usual case.",
                    ],
                ),
                "bazzite_controller_probe_seconds": OptionSpec(
                    type="int",
                    required=False,
                    default=20,
                    description=[
                        "How long controller_probe listens for button presses, in seconds.",
                        "A TIMEOUT rather than a press count, because a pad whose buttons are",
                        "not arriving at all is exactly the case being investigated — waiting",
                        "for N presses would hang forever on the interesting failure. 20s is",
                        "enough for four deliberate presses by someone reading the prompt, and",
                        "short enough that a run with nobody at the pad is not a long wait.",
                        "A timeout is right for ANY caller, so this has a role default (unlike",
                        "a value describing the machine, which belongs in inventory).",
                    ],
                ),
                "bazzite_fan_sweep_pump_headers": OptionSpec(
                    type="list",
                    elements="int",
                    required=False,
                    default=[],
                    description=[
                        "Headers driving a PUMP rather than a fan. The sweep REFUSES these.",
                        "Sweeping searches downward for the duty at which a fan stops, which on",
                        "a pump risks cavitation and loss of coolant flow — and a pump's RPM",
                        "says nothing about whether coolant is actually moving. Empty by",
                        "default because a role cannot know what is plugged into a board; the",
                        "inventory declares it, and declaring nothing means the",
                        "role refuses nothing.",
                    ],
                ),
                "bazzite_fan_sweep_path": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/local/bin/iaac-fan-sweep",
                    description="Where the sweep helper is installed on the target.",
                ),
                "bazzite_fan_sweep_results": OptionSpec(
                    type="str",
                    required=False,
                    default="/var/tmp/iaac-fan-sweep.json",
                    description=[
                        "Where the sweep writes its per-step results. /var/tmp rather than /tmp",
                        "so a result survives a reboot for later comparison.",
                    ],
                ),
                "bazzite_rgb_identify_phase": OptionSpec(
                    type="str",
                    required=False,
                    default="solid",
                    choices=["solid", "chase", "restore"],
                    description=[
                        "solid: one distinct colour per header, held, so the groups can be",
                        "named. chase: walk a single lit LED along a chain so LEDs per fan can",
                        "be counted and the end of each fan seen. restore: back to one colour.",
                    ],
                ),
                "bazzite_rgb_identify_match": OptionSpec(
                    # No default: which device to drive is a fact about the machine.
                    type="str",
                    required=False,
                    description=[
                        "Device-name substring to drive (required by lighting_identify). Matches EVERY controller with that",
                        "name — OpenRGB enumerates the board twice (I2C and HID) and only one",
                        "index actually drives the hardware, so writing to both is what stops a",
                        "live header being mistaken for an empty one.",
                    ],
                ),
                "bazzite_rgb_identify_zone": OptionSpec(
                    type="int",
                    required=False,
                    default=-1,
                    description="chase: which header (0-2). -1 walks each header in turn.",
                ),
                "bazzite_rgb_identify_step": OptionSpec(
                    type="float",
                    required=False,
                    default=0.6,
                    description="chase: seconds each LED stays lit. Slow enough to follow by eye.",
                ),
                "bazzite_rgb_identify_loops": OptionSpec(
                    type="int",
                    required=False,
                    default=3,
                    description=[
                        "chase: how many times to walk each chain. A single pass finishes",
                        "before you have reached the case, so the default repeats.",
                        "0 loops forever — use it with a generous timeout when you want the",
                        "pattern still running while you look.",
                    ],
                ),
                "bazzite_rgb_identify_timeout": OptionSpec(
                    type="int",
                    required=False,
                    default=600,
                    description=[
                        "Seconds allowed for an identify run (the task-level timeout). A chase",
                        "needs roughly LEDs x step x loops; loops 0 runs until this expires.",
                    ],
                ),
                "bazzite_rgb_profile": OptionSpec(
                    type="str",
                    required=False,
                    default="iaac",
                    description=[
                        "OpenRGB profile loaded by the SDK server at startup, and saved to",
                        "after a zone resize.",
                        "Zone SIZES live only in a profile — OpenRGB does not keep them in its",
                        "main config — so without one every server restart reverts addressable",
                        "headers to 0 LEDs, and a zero-LED zone is silently skipped by every",
                        "write. Empty disables profile handling.",
                    ],
                ),
                "bazzite_rgb_zone_sizes": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "LED counts for addressable zones that cannot report their own length,",
                        "as 'name-substring=z0,z1,z2'. Separate devices with ';'.",
                        "A motherboard ARGB header reports leds_count=0 until told what is",
                        "plugged into it, and a zero-LED zone is silently skipped by every",
                        "write — so fans keep running their BIOS effect while everything else",
                        "obeys the daemon, with nothing appearing to fail.",
                        "Count EVERY LED daisy-chained on the branch, including an AIO pump.",
                        "Over-counting is harmless; under-counting leaves the tail unlit.",
                    ],
                ),
                "bazzite_rgb_daemon_mode": OptionSpec(
                    type="str",
                    required=False,
                    default="auto",
                    choices=["static", "cpu", "gpu", "load", "auto"],
                    description=[
                        "What the lighting follows. 'auto' uses whichever of CPU/GPU is",
                        "proportionally hotter, which is usually what you want — the signal of",
                        "interest is 'something is working hard', not which chip you picked.",
                        "'static' holds a fixed bazzite_rgb_color.",
                    ],
                ),
                "bazzite_rgb_daemon_path": OptionSpec(
                    type="str",
                    required=False,
                    default="{{ ansible_env.HOME }}/.local/bin/iaac-openrgb-daemon",
                    description="Where the daemon script is installed on the target.",
                ),
                "bazzite_rgb_server_unit": OptionSpec(
                    type="str",
                    required=False,
                    default="openrgb-server.service",
                    description="User unit name for the OpenRGB SDK server.",
                ),
                "bazzite_rgb_daemon_unit": OptionSpec(
                    type="str",
                    required=False,
                    default="iaac-rgb.service",
                    description="User unit name for the reactive RGB daemon.",
                ),
                "bazzite_rgb_server_host": OptionSpec(
                    type="str",
                    required=False,
                    default="127.0.0.1",
                    description=[
                        "Bind address for the SDK server. Loopback by default: the protocol has",
                        "NO authentication, so anything that can reach the port can drive the",
                        "hardware.",
                    ],
                ),
                "bazzite_rgb_server_port": OptionSpec(
                    type="int",
                    required=False,
                    default=6742,
                    description="TCP port for the SDK server (OpenRGB's default).",
                ),
                "bazzite_rgb_interval": OptionSpec(
                    type="float",
                    required=False,
                    default=2.0,
                    description=[
                        "Seconds between sensor reads. 2s is responsive without pointless I2C",
                        "traffic; DRAM modules are written over SMBus and do not enjoy being",
                        "hammered.",
                    ],
                ),
                "bazzite_rgb_cpu_min": OptionSpec(
                    type="float",
                    required=False,
                    default=35.0,
                    description="CPU temperature (C) mapped to the cold end of the ramp.",
                ),
                "bazzite_rgb_cpu_max": OptionSpec(
                    type="float",
                    required=False,
                    default=85.0,
                    description="CPU temperature (C) mapped to the hot end of the ramp.",
                ),
                "bazzite_rgb_gpu_min": OptionSpec(
                    type="float",
                    required=False,
                    default=30.0,
                    description="GPU temperature (C) mapped to the cold end of the ramp.",
                ),
                "bazzite_rgb_gpu_max": OptionSpec(
                    type="float",
                    required=False,
                    default=85.0,
                    description="GPU temperature (C) mapped to the hot end of the ramp.",
                ),
                "bazzite_rgb_static_modes": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=["Direct", "Static", "Custom"],
                    description=[
                        "Mode names meaning 'show exactly the colour given', in preference order.",
                        "Each device is set using the FIRST of these that it actually declares:",
                        "some RGB DDR5 controllers want 'Direct' and reject 'static', while some",
                        "keyboards offer only 'Static' — so no single hardcoded name works everywhere.",
                        "'Direct' is first because it bypasses onboard effect processing.",
                    ],
                ),
                "bazzite_steam_guard_allow": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=[],
                    description=[
                        "Exact IPv4 addresses allowed to call the Steam guard's endpoint (restart",
                        "and status). INVENTORY CONFIG — declare it per host; the entrypoint",
                        "refuses an empty list. Enforced by the guard on the peer address, because",
                        "the FedoraWorkstation firewalld zone admits every port above 1024.",
                    ],
                ),
                "bazzite_steam_guard_mode": OptionSpec(
                    type="str",
                    required=False,
                    default="observe",
                    choices=["observe", "enforce"],
                    description=[
                        "'observe' logs WOULD RESTART and acts on nothing; 'enforce' restarts a",
                        "dead Game Mode Steam. The endpoint honours an explicit request in both.",
                    ],
                ),
                "bazzite_steam_guard_restart_on_stuck_suspend": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Restart Steam when its UI is stuck mid-suspend, EVEN IN observe mode.",
                        "The signature is read from Steam's webhelper_js.txt: a suspend it",
                        "prepared for while the sleep targets are masked (so no resume can",
                        "come), or Steam ignoring a request because one is 'in progress'. Its",
                        "symptom is a black main page with working menus.",
                        "It still waits bazzite_steam_guard_unhealthy_for",
                        "and counts against bazzite_steam_guard_max_restarts.",
                    ],
                ),
                "bazzite_steam_idle_suspend_ac_seconds": OptionSpec(
                    type="int",
                    required=False,
                    default=-1,
                    description=[
                        "The value Steam's Settings -> Power -> 'Sleep after' must hold, as",
                        "Steam stores it: IdleSuspendACSeconds in ~/.local/share/Steam/config/",
                        "config.vdf (0 = Disabled). -1 = not checked. An ABSENT key means",
                        "Steam's default of 3600 s, which is why a 1-hour idle sleep is",
                        "invisible to a grep of config.vdf.",
                        "CHECKED, NOT WRITTEN: Steam keeps config.vdf in memory and rewrites it",
                        "from memory, so an edit made while Steam runs is lost on its next save.",
                        "The sleep_inhibit entrypoint fails on drift and says to set it in the",
                        "UI; an alert on refused suspends, where one exists, covers the time in between.",
                    ],
                ),
                "bazzite_steam_guard_port": OptionSpec(
                    type="int",
                    required=False,
                    default=8090,
                    description="TCP port the Steam guard's endpoint listens on.",
                ),
                "bazzite_steam_guard_path": OptionSpec(
                    type="str",
                    required=False,
                    default="{{ ansible_env.HOME }}/.local/bin/iaac-steam-guard",
                    description="Where the Steam guard script is installed on the target.",
                ),
                "bazzite_steam_guard_unit": OptionSpec(
                    type="str",
                    required=False,
                    default="iaac-steam-guard.service",
                    description="User unit name for the Steam guard.",
                ),
                "bazzite_steam_guard_session_unit": OptionSpec(
                    type="str",
                    required=False,
                    default=(
                        # `| default(...__default)`: the generated resolver sets every option
                        # in ONE set_fact, where a sibling option is not yet defined.
                        "{{ 'gamescope-session-plus@' ~ ((bazzite_game_session"
                        " | default(bazzite_game_session__default))"
                        " | regex_replace('^gamescope-session-', '')"
                        " | regex_replace('[.]desktop$', '')) ~ '.service' }}"
                    ),
                    description=[
                        "The Game Mode session user unit the guard watches and restarts. It owns",
                        "Steam, its streaming listeners and the compositor together.",
                        "DERIVED from bazzite_game_session, because the unit name follows the",
                        "session: gamescope-session-steam.desktop runs `gamescope-session-plus",
                        "steam` -> gamescope-session-plus@steam.service, and the OGUI session",
                        "runs @ogui-steam.service (read from the .desktop Exec= lines).",
                        "A hard-coded @steam would leave the guard and the Deck's",
                        "restart tile pointed at a unit that is not running.",
                    ],
                ),
                "bazzite_steam_guard_interval": OptionSpec(
                    type="int",
                    required=False,
                    default=30,
                    description="Seconds between the watchdog's observations.",
                ),
                "bazzite_steam_guard_unhealthy_for": OptionSpec(
                    type="int",
                    required=False,
                    default=180,
                    description=[
                        "Seconds Steam must stay broken, continuously, before the watchdog acts —",
                        "long enough to ride out a client restart that Steam performs itself.",
                    ],
                ),
                "bazzite_steam_guard_startup_grace": OptionSpec(
                    type="int",
                    required=False,
                    default=300,
                    description=[
                        "Seconds after any restart (and after the guard starts) during which it",
                        "will not act, and before a closed Remote Play port counts as a fault.",
                    ],
                ),
                "bazzite_steam_guard_max_restarts": OptionSpec(
                    type="int",
                    required=False,
                    default=6,
                    description="Most AUTOMATIC restarts allowed per bazzite_steam_guard_window.",
                ),
                "bazzite_steam_guard_window": OptionSpec(
                    type="int",
                    required=False,
                    default=10800,
                    description="Rate-limit window in seconds (10800 = 3 hours).",
                ),
                "bazzite_session_report_connector": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "DRM connector directory under /sys/class/drm whose HDR metadata,",
                        "colorspace and max_bpc the session_report entrypoint prints, e.g.",
                        "'card1-HDMI-A-1'. Empty (the default) reads every CONNECTED connector,",
                        "because the card index and connector name differ between machines and",
                        "a hard-coded path reads nothing on any other one.",
                    ],
                ),
                "bazzite_probe_save": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description="Write the probe survey to disk as well as reporting it.",
                ),
            },
        ),
    }
)
