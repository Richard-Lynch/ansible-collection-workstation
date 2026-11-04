<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to this collection are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the collection
uses [Semantic Versioning](https://semver.org/).

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
