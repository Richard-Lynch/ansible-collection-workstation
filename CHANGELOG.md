<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to this collection are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the collection
uses [Semantic Versioning](https://semver.org/).

## [1.2.0] — 2026-11-20

### Added

- `bazzite_workstation`: `bazzite_rgb_brightness` now takes effect. The RGB daemon takes `--brightness` and scales every colour it writes, in every mode, including the temperature ramp. The option is now a float; an integer value is still valid.
- `bazzite_workstation`: breathing, with `bazzite_rgb_breathe_depth` (percentage points either side of the brightness, default `0` = off), `bazzite_rgb_breathe_period` (seconds, default `4.0`) and `bazzite_rgb_breathe_rate` (render ticks per second, default `20.0`). The render tick is separate from the sensor poll, and static mode breathes too. With depth `0` the daemon writes exactly as often as before.
- `bazzite_workstation`: the `lighting` entrypoint refuses an out-of-range or non-numeric brightness or breathing value before writing anything, rather than installing a unit that would fail at startup; the daemon refuses the same values itself.

### Fixed

- `bazzite_workstation`: restarting the OpenRGB SDK server no longer leaves the previous server running. `flatpak run` moves the server into a transient scope outside the unit, so a unit restart killed only the wrapper; the old server kept the port and every new instance crash-looped on bind. The unit now runs `flatpak kill` before start and after stop, a server-unit change stops every OpenRGB scope and proves the process table and port are empty before starting, and `lighting` asserts one server process, one listener and an unchanged restart counter over a settle window (`bazzite_rgb_settle_seconds`).
- `bazzite_workstation`: the RGB daemon exits promptly on SIGTERM. Its waits returned only when they expired, so a stop during static mode's 60 s hold outlived systemd's stop timeout and ended in SIGABRT.
- `bazzite_workstation`: a socket error while writing colours now reaches the daemon's reconnect, instead of being logged per device and per write against a dead connection.
- `bazzite_workstation`: the `lighting` report shows the colour as written at the configured brightness, not only the unscaled target.

### Removed

- `bazzite_workstation`: `bazzite_rgb_mode`, an option nothing read. No task, template or daemon argument used its value, so setting it changed nothing. A device's hardware effect replaces the per-LED mode the daemon writes in, so it could not follow the temperature ramp or be dimmed by the daemon; breathing covers that use. This is a minor release rather than a major one because no behaviour is removed: a caller that still sets the variable gets exactly what it got before, which was nothing.

## [1.1.0] — 2026-11-04

### Added

- Role `bazzite_workstation`: post-install setup for a Bazzite gaming workstation (flatpaks, gaming tunables, optional layering, image tracking and gated rebase), Game Mode session, autologin, sleep inhibition, HDMI-CEC, Sunshine streaming, OpenRGB lighting, Super-I/O fan sweeps and curves, Wake-on-LAN and a Steam watchdog, plus read-only reports that compare the live process against its configuration. Every write reports first and acts only behind an explicit apply or confirm flag.
- Every machine-specific value (user, hostname, Super-I/O chip, RGB controller, DRM connector, 1Password use, fan curves, image variant) is an option with no machine-specific default.

## [1.0.0] — 2026-11-03

### Added

- Role `config_fan_control`: fan curves from hwmon sensors, with a reported dry run first.
- Roles `rpi_boot_media`, `rpi_image_media`, `rpi_host_setup` and `rpi_fleet_report`: Raspberry Pi boot media, first-boot image seeding, host setup and a fleet report.
- Roles `usb_media` (bootable USB media with a verified write) and `asus_tuf_b850m_bios` (BIOS flashing media for one specific board, checksum-verified).
- Every estate-specific value is a required option with no default.
