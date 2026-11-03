# rpi_boot_media

Owns which device a Raspberry Pi 4 boots from, and the state of its two media.

## The model

| Medium | Role |
|---|---|
| **SD card** | A near-immutable **rescue shell** — read-only via overlayfs, out of the normal boot path. Its job is to give the operator a way onto a board whose SSD path has failed. Not a backup. |
| **USB3 SSD** | The read-write root that carries the workload. |

The board's EEPROM `BOOT_ORDER=0xf714` (USB SSD -> SD card -> HTTP install -> loop; generate it
with `files/rpi_boot_order.py ssd card http`, never by hand) prefers USB and falls back to the
card. Recovery is *boot the
card, re-provision the SSD, re-run the plays* — these hosts are stateless, so Ansible is the backup.

## Entrypoints

| `rpi_boot_action` | Writes | Does |
|---|---|---|
| `probe` | no | What this board is, what it boots from, what is attached |
| `eeprom_report` | no | Decodes `BOOT_ORDER` into plain English |
| `eeprom` | **firmware** | Converges the boot order |
| `provision_ssd` | **DESTROYS the SSD** | Images the SSD from the pinned OS image and expands root |
| `harden_sd` | yes | Seals the rescue card read-only |
| `watchdog` | yes | Hardware watchdog + `panic=` |
| `verify` | no | Post-reboot: is root the SSD, is the card sealed, is the watchdog armed |
| `rollback` | yes | Boot order back to SD-first; disarms the watchdog |

Every writing action is gated on `rpi_boot_apply`; `provision_ssd` additionally needs
`rpi_boot_confirm`, because "make changes" and "erase that disk" are different statements.

## The order is not the obvious one

```
probe → (DHCP reservation) → baseline → harden_sd → provision_ssd → eeprom → reboot → verify → watchdog
```

Two steps are counter-intuitive, and both fail **silently** if reversed:

1. **`harden_sd` runs BEFORE the migration**, while the SD is still the running root. overlayfs is
   enabled against the *running* system — run it afterwards and it hardens the **SSD**, destroying
   the primary system's persistence while every assertion still passes, because they read the file
   that was wrongly edited. The role refuses when the target is not the current root's disk;
   ordering is a human-fallible guarantee, a device-identity refusal is not.
2. **`eeprom` runs AFTER the SSD is verified.** Pi firmware falls back to the card only when it
   cannot *load* boot files from USB. Once the SSD's boot partition is loadable, USB-first means
   the firmware commits — and a kernel that cannot mount a half-written root just hangs, with a
   perfectly good rescue card in the slot, preempted.

## Safety notes

- **The watchdog bound is enforced, not documented.** `rpi_watchdog_runtime_sec` is capped at 15 in
  the argspec: the BCM hardware cannot accept more, and larger values have produced continuous
  reboot loops — a misconfigured watchdog is a fleet-wide outage.
- **`panic=` is a second, separate mechanism.** A kernel panic at root-mount happens *before*
  systemd arms the watchdog, so `RuntimeWatchdogSec` can never fire for it. That is precisely the
  corrupt-SSD case.
- **Live state is only asserted by `verify`.** Every writing action here takes effect at the next
  boot, so none can legitimately assert its own result — doing so would pass on an unchanged system
  and keep passing forever.
- **Config files are never trusted for verification.** `/proc/cmdline` is read rather than
  `cmdline.txt`, because the firmware injects arguments that never appear in that file.

## Inputs

See `meta/argument_specs.yml` (generated — edit `meta/argument_specs.py`).

`rpi_boot_ssd_by_id` is **required with no default**: kernel names renumber between boots, and for
an action that repartitions a disk, "nobody declared it" must stop the play rather than proceed on
a guess.

## What it deliberately does NOT do

- Deploy services. Containers, log shipping and alert rules belong to the roles that own them.
- Clone the SD card onto the SSD. The SSD is imaged from the same pinned image and converged by
  plays, which removes the PARTUUID/label/machine-id hazard class entirely rather than guarding it.
- Edit a hardened card in place. The card is write-once; it is re-imaged when it must change.
