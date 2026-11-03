<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to this collection are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the collection
uses [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-11-03

### Added

- Role `config_fan_control`: fan curves from hwmon sensors, with a reported dry run first.
- Roles `rpi_boot_media`, `rpi_image_media`, `rpi_host_setup` and `rpi_fleet_report`: Raspberry Pi boot media, first-boot image seeding, host setup and a fleet report.
- Roles `usb_media` (bootable USB media with a verified write) and `asus_tuf_b850m_bios` (BIOS flashing media for one specific board, checksum-verified).
- Every estate-specific value is a required option with no default.
