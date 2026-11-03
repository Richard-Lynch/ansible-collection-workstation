# usb_media

Inspect, benchmark, verify and write USB install media on **macOS**.

Written for building an installer stick from a macOS controller (Bazzite is the worked example),
but nothing in it is Bazzite-specific — any isohybrid image works.

## Entrypoints

| `tasks_from` | Does | Destructive |
|---|---|---|
| `list` | enumerate attached disks, say which are eligible targets | no |
| `inspect` | identify and vet ONE device | no |
| `benchmark` | burst + sustained throughput, with an 8GB write estimate | write only |
| `integrity` | prove the device stores what is written to it | yes |
| `random_io` | scattered 4KiB latency/verification; wear-tail signal | yes |
| `retention` | write, wait, re-read — catches cells that decay over time | yes |
| `write` | download, verify and block-copy an installer image | yes |

`main.yml` dispatches on `usb_media_action` for callers who prefer that; `tasks_from` is the
direct route. Every destructive entrypoint is gated on the same `usb_media_apply` flag.

**`resolve_device.yml` is the single source of truth for the safety gate.** It is included, never
copied — a gate living in three files is one that will disagree with itself after the third edit,
and the disagreement gets discovered by a destroyed disk rather than by a test.

## Why the ceremony

The dangerous operation is one `dd`, and `/dev/disk4` vs `/dev/disk2` is a one-character mistake
that silently destroys the controller's own disk. So:

- **Generate-don't-apply.** A default run reports what it *would* overwrite and stops.
  The write happens only with `usb_media_apply=true`.
- **Four independent safety conditions**, asserted together before any write, none of them
  bypassable by a flag. `usb_media_apply` means "yes, write" — never "yes, ignore these".
- **A read-back after the write**, because `dd` exits 0 on a short write to a failing stick.

## Inputs

See `meta/argument_specs.yml` (generated — edit `meta/argument_specs.py`).

Required: `usb_media_iso_url`, `usb_media_checksum_url`, `usb_media_device`.

`usb_media_device` must be a **whole-disk** node (`/dev/disk4`), never a partition (`/dev/disk4s1`)
and never a raw node (`/dev/rdisk4`) — the raw node is derived internally for the write itself.

## Usage

```yaml
- name: Build the install media
  ansible.builtin.include_role:
    name: richard_lynch.workstation.usb_media
    tasks_from: write
  vars:
    usb_media_iso_url: "https://download.bazzite.gg/bazzite-stable-amd64.iso"
    usb_media_checksum_url: "https://download.bazzite.gg/bazzite-stable-amd64.iso-CHECKSUM"
    usb_media_device: /dev/disk4
    usb_media_apply: true
```

Typical wrapper plays: one that runs `list` to show eligible targets, one that runs the health
entrypoints (identity, throughput, integrity), and one per image you build media for.

## The safety gate

A write is refused unless **all four** hold:

| Condition | Why |
|---|---|
| not `Internal` | never the boot disk or other internal media |
| `Removable` (defaults to **false** if the key is absent) | an absent key must block, not allow |
| `WholeDisk` | writing an ISO to a partition yields a stick that silently will not boot |
| image size ≤ device size ≤ `usb_media_max_device_bytes` | a typo cannot select a large external backup drive |

Raise `usb_media_max_device_bytes` (default 128GB) only for a genuinely larger stick.

### The identity token — for writing several similar devices

Those four conditions authenticate a **class** of device, not an **identity**. Every card in a
batch of identical SD cards passes all four, so `/dev/disk4` vs `/dev/disk5` is a one-character
mistake nothing above can catch.

`usb_media_device_confirm` closes that gap: when set, the device must match it (compared against
the identifiers `diskutil`/IOKit report — serial, media name, volume name, UUID). It is optional,
so existing callers are unchanged, and **fail-closed**: a device that reports no readable identity
is a refusal, never a skip.

> **Know what it does NOT distinguish.** For a card in a USB reader, macOS reports the **reader's**
> serial, not the card's — so two different cards in the same reader carry the **same** token. This
> tells apart devices and slots, not cards. To tell apart cards, check their **content** (e.g. a
> seeded hostname on the boot partition).

## Compressed images (`.img.xz`)

`usb_media_decompress=true` expands the download before writing. Needed for Raspberry Pi OS, which
ships as `.img.xz` — `dd`-ing the compressed file produces a card that simply does not boot, with
no other symptom.

The order is the design, and it is why this is a flag rather than a `xz -dc | dd` pipe:

```
download → verify the ARCHIVE against the published sha → decompress → write → read back
                                                                        against the DECOMPRESSED image
```

The published checksum is of the *compressed* file, so it can only be checked before decompression;
every post-write verification then compares against the *decompressed* image, because that is what
is actually on the card. A stream would discard the decompressed size and hash that those checks
need, and would hide a mid-pipe failure behind `dd`'s exit status.

Decompression is idempotent (`creates:`) and keeps the original (`-k`), so a re-run neither
re-expands a multi-GB image nor forces a re-download to re-verify it.

## Notes on the implementation

- **`diskutil info` is parsed via `plutil` into JSON.** Ansible has **no `from_plist` filter** —
  `ansible.builtin.from_plist` does not exist. `plutil` ships with macOS.
- **The checksum is parsed by regex, not `sha256sum -c`.** macOS has no guaranteed GNU
  `sha256sum`, and upstream's CHECKSUM file [shipped for several releases][3793] with the build
  runner's absolute path in the filename field, which breaks `-c` on a perfectly good download.
  The hash is selected by matching the ISO **name**, so a multi-variant checksum file cannot yield
  another image's hash.
- **No `\b` in that regex, deliberately.** In a folded (`>-`) YAML scalar `'\\b'` reaches the
  regex engine as a literal double-backslash and silently matches nothing, while the same text in
  a double-quoted scalar is correct. `[0-9a-f]{64}` needs no boundary.

[3793]: https://github.com/ublue-os/bazzite/issues/3793

## The three throughput/capacity tiers

Consumer flash absorbs roughly the first GB of a write into a fast SLC cache, then falls back to
its native rate. A short benchmark measures only the cache and overstates a real image write —
for example, measured on one USB 3 stick: **69.0 MB/s at 256MB, 68.1 at 1GB, then 39.8 at 2GB**, a 42%
drop entirely invisible to the short test.

| Tier | Var | Cost | Answers |
|---|---|---|---|
| burst | `usb_media_bench_mb` (256) | seconds | what the SLC cache does |
| **sustained** | `usb_media_sustained_mb` (2048) | ~50s | **what a real 8GB write will do** |
| full capacity | `usb_media_full=true` | ~30min+ | is the reported size real |

The middle tier is the default for `benchmark`, and the time estimate is derived from it — not
from the burst figure, which is how "about 2 minutes" turns into four. The full tier answers a
different question (capacity, not speed) and belongs to `integrity`.

**Results depend on how recently the stick was written to.** The same stick measured 69 MB/s
burst when rested and 27 MB/s burst a few minutes after several GB of back-to-back writes — its
SLC cache had had no idle time to flush. For a clean baseline, let the stick sit for a minute or
two before benchmarking. Nothing in the role tries to compensate for cache state: a benchmark
that silently adjusted its own numbers would be worse than one that reports what it measured.

## What "health" can and cannot mean for a USB stick

USB thumb drives expose **no SMART data** — verified on SanDisk sticks:
`diskutil info` reports `SMARTStatus: Not Supported`, and they enumerate as plain USB Mass
Storage (`Peripheral Device Type 0`), not SATA bridges, so there is no ATA command set for
`smartctl` to pass through. Installing smartmontools would not help. `diskutil verifyDisk` only
validates a partition map, and `fsck` only a filesystem — neither says anything about the flash.

So every health signal here has to be produced by exercising the device:

| Entrypoint | Catches | Blind to |
|---|---|---|
| `benchmark` | crippled controller, wrong link speed | the flash itself |
| `integrity` (sparse) | discard-mode counterfeit capacity | ~99.9% of blocks; wrapping fakes |
| `integrity` (`usb_media_full=true`) | bad blocks anywhere; proves the real size | faults that appear later |
| `random_io` | read-modify-write stalls, worn-block latency tails | sequential-only faults |
| `retention` | cells that accept a write then lose it | intervals longer than the one tested |

**Still not covered**, and honest to say so: repeated write/erase cycling (finds cells that fail
under stress, but genuinely consumes device lifespan), and thermal/voltage stress. `f3` — the
Linux "Fight Flash Fraud" tool — covers the same capacity-fraud ground as `integrity`.

The sparse integrity verdict deliberately states the fraction it sampled, because "PASSED" over
0.1% of a device is not a health clearance and should not read like one.

## Retention testing, and the two traps in it

`retention` is the only check that can see a cell which accepts a write, reads back correctly,
and loses its charge hours later — every other test here verifies immediately and is blind to it.

Run it in two phases for a meaningful interval:

```
# today
... tasks_from: retention   usb_media_retention_phase=write
# tomorrow — same usb_media_retention_state path
... tasks_from: retention   usb_media_retention_phase=verify
```

`usb_media_retention_phase=wait` (the default) writes, sleeps, and verifies in one run — convenient,
but bounded by how long you will sit there. Minutes catch only gross faults.

**Do not write to the device between the phases**, including with another run of this test. Both traps
below are detected rather than mis-reported:

- Blocks carrying a **different nonce** mean something overwrote them, so the verdict is
  `INCONCLUSIVE` — a spoiled measurement, not evidence about the hardware. Reporting that as
  decay would condemn a perfectly good stick.
- The nonce is `timestamp-urandom`, not a bare timestamp. Two runs starting in the same second
  would produce identical nonces and identical block content, so a verify would report a false
  PASS on data another run had overwritten.

## Testing

A molecule scenario that runs the **real role** against fake
`diskutil`/`dd`/`sync` binaries and a file standing in for the stick (no root, no real disk) is
the way to test it.

Each fixture device violates **exactly one** safety condition, and `verify.yml` asserts *which*
assertion fired, not merely that something did. This was arrived at the hard way: the first
fixture used realistic devices that broke several rules at once, and defeating the `Internal`
check as a test left the suite green because the `Removable` check caught the same device.

The suite is **mutation-tested**: stubbing out any one of the four safety conditions, the
checksum comparison, the read-back, or the apply guard turns it red. Two fixtures exist purely
so that a check has something to catch — a check the fixture cannot exercise is untestable, and
both of these initially survived mutation:

| Fixture | Makes testable |
|---|---|
| `corrupt.iso` served with a deliberately wrong CHECKSUM | the checksum comparison |
| `FAKE_SHORT_WRITE=1` — fake `dd` writes wrong bytes, exits 0 | the post-write read-back |

## What this role deliberately does NOT do

- It does not partition, format, or shrink anything. The ISO is written as a flat block copy,
  which is the supported method for an isohybrid image; UEFI needs nothing further.
- It does not touch any disk in the *target* machine, and does not automate an OS install.
- It is **macOS-only**. It shells out to `diskutil`/`plutil` and assumes `/dev/rdiskN` naming.
  A Linux equivalent would need `lsblk` and `/dev/sdX` and is not attempted here.
