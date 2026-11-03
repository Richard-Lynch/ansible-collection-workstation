# asus_tuf_b850m_bios

BIOS management for **one specific board**: the ASUS TUF GAMING B850M-PLUS WIFI7 **W**.

Deliberately narrow. ASUS sells at least seven near-identical B850M variants, and
"TUF GAMING B850M-PLUS WIFI7" and "…WIFI7 **W**" are different products with different
ProductIDs (33373 vs 32356) and non-interchangeable firmware. A generic "ASUS BIOS" role would
carry that ambiguity into every call; specialising removes it.

## Entrypoints

| `asus_bios_action` | Does | Writes |
|---|---|---|
| `list` | live version table + drift vs the pinned one | nothing |
| `verify` | confirm the pinned ProductID against ASUS's live API | nothing |
| `download` | fetch a version, verify its SHA-256 | one file |

```bash
ansible-playbook asus_bios.yml -e asus_bios_action=list
ansible-playbook asus_bios.yml -e asus_bios_action=verify
ansible-playbook asus_bios.yml -e asus_bios_action=download -e asus_bios_apply=true
```

## How the data is actually obtained

Established by watching the page's own network traffic in a browser, not by guessing endpoints.

**The support page is a Nuxt SSR app and makes no request for BIOS data** — it is rendered
server-side into the HTML. Every "find the API" approach fails because there is no API call to
find.

The decisive detail: the **`?model2Name=` form** of the URL returns the full ~566KB payload with
every version and SHA-256 embedded. The trailing-slash form returns a ~17KB client-rendered
shell. That one query parameter is the difference between no data and all of it.

### Does ASUS have a real API? Yes — but not for this board

`rog.asus.com/support/webapi/product/GetPDBIOS` is genuine and current, returning `Version`,
`sha256`, `DownloadUrl`, `ReleaseDate` and `IsRelease`. Confirmed working (`Status: SUCCESS`)
against a ROG laptop.

It is keyed on **`LevelTagId`, not `pdid`** — passing a laptop's LevelTagId with this board's
pdid returns *the laptop's* firmware. No LevelTagId exists for TUF motherboards, and no
level-discovery endpoint could be found. **That API serves ROG laptops, not this board.**

`www.asus.com/support/api/product.asmx/GetPDBIOS` is a **legacy** endpoint the current site no
longer calls; it answers every request with the same hardcoded default product regardless of
parameters. Building on it would silently serve another board's firmware.

### So: parse live, pin the URLs

`files/parse_bios_page.py` fetches the SSR page and extracts version, date, size, SHA-256,
release notes, rollback flags and the FlashBack filename. It anchors on **stable CSS class
prefixes** (the trailing hashes change per build), so a page restructure yields *zero* rows
rather than wrong ones — and `list` asserts on that.

**Download URLs stay pinned.** They are constructed client-side, appear nowhere in the payload,
and were verified by HTTP HEAD. Versions whose URL 404s are flagged `url_unverified` and the
download entrypoint refuses them.

## Safety properties

- **Checksum drift is a hard failure.** If a version exists in both tables with different hashes,
  `list` fails — verifying a download against a wrong hash is worse than not verifying.
- **Betas are refused** unless `asus_bios_allow_beta=true`. Several versions of this BIOS
  **cannot be rolled back**, making a beta flash permanent.
- **Unknown versions are refused** rather than downloaded unverified.
- **A failed live check is reported**, never treated as "no new versions".
- The ProductID is **verified against ASUS's live search API**, which does honour its query —
  mutation-tested: a wrong pin fails, and the non-W board name resolves to the other ID.

## Version guidance

**1681 (stable)** is recommended over 1686 (beta). The only difference is GNR TSME, a server
memory-encryption feature irrelevant to a desktop — and with rollback blocked, "latest beta"
would be a permanent decision for no gain. 1681 also adds EXPO ULL profiles and ECC-UDIMM
optimisation.

## Flashing

Prepare the stick first (the `usb_media` role in this collection can) — firmware needs
**FAT32 + MBR**, which an ordinary format does not produce.

- **EZ Flash 3** (in-BIOS, needs working CPU/RAM): keep the filename as downloaded.
- **BIOS FlashBack** (no CPU/RAM/GPU needed): rename with the bundled `BIOSRenamer.exe`
  (this board's target name is `A5695.CAP`), use the dedicated rear USB port, hold the button ~3s.

After flashing, firmware settings are typically reset — re-check EXPO, AHCI, ReBAR, Above 4G
Decoding and Secure Boot.
