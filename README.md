<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# richard_lynch.workstation

Workstation and device roles: per-component fan control, Raspberry Pi boot media, image seeding, host setup and fleet reports, bootable USB media, and BIOS flashing media for one ASUS board.

## Roles

| Role | Description |
| ---- | ----------- |
| `asus_tuf_b850m_bios` | BIOS management for the ASUS TUF GAMING B850M-PLUS WIFI7 W |
| `config_fan_control` | Fan control by normalised per-component thermal demand |
| `rpi_boot_media` | Pi 4 boot media: EEPROM order, SSD provisioning, rescue-card sealing |
| `rpi_fleet_report` | Whole-fleet drift report for the Pi nodes |
| `rpi_host_setup` | Per-Pi OS baseline: identity, packages, USB quirks, cgroups |
| `rpi_image_media` | Seed a written Pi card for a fully headless first boot |
| `usb_media` | Inspect, benchmark, verify and write USB install media on macOS |

## Install

```sh
ansible-galaxy collection install richard_lynch.workstation
```

or pin it in `requirements.yml`:

```yaml
collections:
  - name: richard_lynch.workstation
    version: "1.0.0"
```

Requires ansible-core >=2.19.0.

## Development

```sh
# from a checkout at ansible_collections/richard_lynch/workstation
ansible-test sanity --docker
ansible-test units --docker
ansible-galaxy collection build
devkit conform                  # the repository standard (ansible-devkit)
devkit check all                # the static checks, configured by devkit.toml
```

CI, the disclosure gate and releases are the shared workflows of
[ansible-devkit](https://github.com/Richard-Lynch/ansible-devkit), called from
`.github/workflows/` at tag `v0.2.3`. A release is a merged pull
request that bumps `version` in `galaxy.yml` and adds the matching
`CHANGELOG.md` section. `export.manifest` lists every tracked path; update it in
the same commit as any file added or removed.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
