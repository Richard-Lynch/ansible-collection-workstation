# rpi_image_media

Seeds a freshly written Raspberry Pi card so it boots headlessly and Ansible can reach it.
Runs on the **controller**, not on a Pi.

## Scope — this role seeds ONLY

The `usb_media` role does the dangerous part: the `dd`, the four-condition device gate, and the
post-write read-back. Re-implementing any of that here would create a second source of truth for
"is it safe to write to this disk", which its own README warns about.

```
usb_media (list)                    which /dev/diskN is the card
usb_media (health entrypoints)      is this card fit to BE a rescue system
usb_media (write)                   the image lands on the card
THIS ROLE (seed)                    the card becomes reachable headlessly
```

## Entrypoints

| `rpi_image_action` | Does |
|---|---|
| `plan` | Reports every file that would be written. **Default** — writes nothing |
| `seed` | Writes the first-boot provisioning files |
| `verify` | Re-mounts and asserts each file landed, and that the card is for the intended host |

## Both provisioning mechanisms are seeded, deliberately

Raspberry Pi OS has changed how it provisions a headless first boot: current images read
`custom.toml`, older ones read `userconf.txt` plus an empty `ssh` marker — and upstream describes
`custom.toml` as temporary, possibly to be replaced by cloud-init.

Guessing wrong **fails silently**: the card boots, ignores the config, and leaves a Pi with no user
and no SSH — which on a headless build means finding a monitor and keyboard. They do not conflict
and cost a few hundred bytes, so both go on, and `verify` reports which one took effect.

## Two refusals that make this design acceptable

An SD card is readable by anyone who physically picks it up. What makes an SD-based rescue system
acceptable is that it carries **only a password hash and a public key** — and that property is easy
to erode by accident. So `seed` refuses:

- anything **private-key-shaped** in `rpi_image_authorized_key`;
- a password that is **not a crypt hash** (plaintext on a card anyone can pick up).

Both are proven to fire in `molecule/default/`.

## Inputs

See `meta/argument_specs.yml` (generated — edit `meta/argument_specs.py`).

Resolve the password hash at run time from a secret store (for example 1Password via
`richard_lynch.common.onepassword_cached`) rather than committing it. Neither the repo nor the
card should ever hold plaintext.
