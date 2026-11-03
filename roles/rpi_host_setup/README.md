# rpi_host_setup

The per-Pi OS baseline: identity, packages, time, bounded logs, USB quirks, cgroups.

Separate from `rpi_boot_media`, which owns boot media and firmware. **This role stops at the OS** —
it deploys no services.

## Entrypoints

| `rpi_host_action` | Writes | Does |
|---|---|---|
| `probe` | no | Model, serial, OS, TRIM support — and asserts board identity |
| `baseline` | yes | Hostname, packages, timezone, journald cap, security updates |
| `usb_quirks` | yes | UAS workarounds for known-bad USB-SATA bridges |
| `cgroups` | yes | The memory controller Docker needs to enforce limits |
| `health_report` | no | Throttling, temperature, disk, kernel I/O errors |
| `all` | yes | baseline + usb_quirks + cgroups |

## Three things worth knowing

**The memory cgroup is disabled by default on Pi OS, and the obvious verification cannot detect
it.** Without it, `docker run --memory=`, `MemoryMax=` and k3s limits are all accepted and
*silently unenforced*. The disable comes from a `cgroup_disable=memory` the **firmware injects**,
which never appears in `cmdline.txt` — so reading that file back proves nothing. Verification reads
`/proc/cmdline` and `/sys/fs/cgroup/cgroup.controllers` instead.

**USB quirks are reactive by design.** `rpi_usb_quirks` is empty by default: blanket-disabling UAS
costs real throughput on adapters that are fine. `rpi_boot_action=probe` reports each bridge's
VID:PID; an entry is declared in inventory only when a specific adapter misbehaves. A malformed
entry is refused, because the kernel would silently ignore it — leaving a workaround that never
applies while inventory shows it configured.

**Board identity is asserted.** `rpi_soc_serial` is required with no default and checked against
`/proc/cpuinfo`. Nothing else ties a hostname to a physical board: two cards seeded with the same
name in two boards produce working reservations and a colliding name in DNS and monitoring.

## Implementation note

`files/rpi_cmdline.py` exists because `cmdline.txt` is a **single line**, and every naive edit has a
specific silent failure: `lineinfile` appends a second line the firmware ignores; a regex replace
can match a substring of an unrelated token (`panic=` inside `nopanic=`). It parses into whole
tokens and reports CHANGED/UNCHANGED so callers can key `changed_when` off the verdict.

## Inputs

See `meta/argument_specs.yml` (generated — edit `meta/argument_specs.py`).
