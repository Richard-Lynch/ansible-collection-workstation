# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

# THE BOARD. Deliberately specific: ASUS sells at least seven near-identical B850M variants, and
# "TUF GAMING B850M-PLUS WIFI7" and "TUF GAMING B850M-PLUS WIFI7 W" are DIFFERENT PRODUCTS with
# different ProductIDs (33373 vs 32356) and non-interchangeable firmware. The trailing "W" is the
# whole distinction. Verified against ASUS's search API — see tasks/discover_product_id.yml.
BOARD = "TUF GAMING B850M-PLUS WIFI7 W"
PRODUCT_ID = 32356

SUPPORT_URL = (
    "https://www.asus.com/uk/motherboards-components/motherboards/tuf-gaming/"
    "tuf-gaming-b850m-plus-wifi7-w/helpdesk_bios/"
)

# Download URL pattern, VERIFIED by HTTP HEAD against the pinned versions when the table was last
# checked (DATA_CHECKED): the versions without url_unverified return 200 at this path. Note the
# UPPERCASE .ZIP — the lowercase form returns 404.
DL = "https://dlcdnets.asus.com/pub/ASUS/mb/BIOS/"

# PINNED VERSION TABLE, with ASUS's own published SHA-256 for each.
#
# Why pinned rather than scraped: ASUS's support pages are client-rendered, and their JSON BIOS
# endpoint (product.asmx/GetPDBIOS) IGNORES the product id — every call returns the same
# hardcoded default board regardless of what is asked for. A scraper built on it would silently
# return another board's firmware. See tasks/list_versions.yml for the full findings.
#
# To add a version: read it from SUPPORT_URL and copy the vendor's SHA-256 verbatim.
VERSIONS = [
    {
        "version": "1686",
        "beta": True,
        "released": "2026-07-02",
        "size": "17.97 MB",
        "sha256": "FC7BBCA50F371B7A2511B7B6C4CB3930CD892033B8141BAA6171D48D3D268C2B",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1686.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1686.ZIP",
        "notes": "AGESA ComboAM5 PI 1.3.0.1b Patch A — GNR Transparent Secure Memory Encryption (TSME).",
        "no_rollback": False,
    },
    {
        "version": "1681",
        "beta": False,
        "released": "2026-06-22",
        "size": "17.97 MB",
        "sha256": "E3FF50224C1569D9232C8A972F09D707FEE68606EFA79E35C09CEBDF88C2BB81",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1681.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1681.ZIP",
        "notes": "AGESA ComboAM5 PI 1.3.0.1b. Adds EXPO ULL memory profiles. Optimises ECC-UDIMM performance.",
        "no_rollback": False,
    },
    {
        "version": "1670",
        "beta": True,
        "released": "2026-04-29",
        "size": "17.95 MB",
        "sha256": "7960F3AD804B2EDC7AA3093134FD6C9C958F2988BC50932DF35E0960C9B84FD4",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1670.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1670.ZIP",
        "notes": "New memory profile support.",
        "no_rollback": False,
    },
    {
        "version": "1654",
        "beta": False,
        "released": "2026-04-27",
        "size": "17.95 MB",
        "sha256": "46E7B23F318C88CA968AE4DA67C6A3446C158CD3D96DECFEBC41980F23EE1E7A",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1654.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1654.ZIP",
        "notes": "AGESA ComboAM5 PI 1.3.0.1. Ryzen 9 9950X3D2 Dual Edition compatibility.",
        "no_rollback": True,
    },
    {
        "version": "1644",
        "beta": False,
        "released": "2026-03-19",
        "size": "17.9 MB",
        "sha256": "9A98DA9FD8D7B386EE300654A27BD00B06F52E94F91BA85BCF7EA4DC8A408873",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1644.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1644.ZIP",
        "notes": "AGESA ComboAM5 PI 1.3.0.0a. DDR5 training stability. Resolves a BitLocker recovery-key issue.",
        "no_rollback": False,
    },
    {
        "version": "1627",
        "beta": False,
        "released": "2026-02-11",
        "size": "17.89 MB",
        "sha256": "516B1D1EF84693F300D1F16C7A34E5A1F359F5C3F30E4E012B706B5137F6E8EA",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1627.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1627.ZIP",
        "notes": "AGESA ComboAM5 PI_Pre1.3.0.0. Memory compatibility for JEDEC modules.",
        "no_rollback": False,
    },
    {
        "version": "1402",
        "beta": False,
        "released": "2025-12-04",
        "size": "17.9 MB",
        "sha256": "6F788EAAB5403E913A4A58CA9F6E76A505D45E1424C92B10B0860BD65E602321",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1402.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1402.ZIP",
        "notes": "AGESA ComboAM5 PI 1.2.7.0. Broader CPU and device compatibility.",
        "no_rollback": True,
        # URL returns 404 at this path — ASUS serves this older release from a different path
        # than the -ASUS-<ver>.ZIP pattern the rest follow. Flagged rather than removed: the
        # checksum is still the vendor's, and a download attempt fails loudly on the 404 rather
        # than silently fetching something else. Find the real URL before using this version.
        "url_unverified": True,
    },
    {
        "version": "1087",
        "beta": False,
        "released": "2025-10-22",
        "size": "15.43 MB",
        "sha256": "C66FC74B1787DF06AABE332E1B4404494F552083841D9AEE8EF3270EFBF3CFA9",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1087.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1087.ZIP",
        "notes": "AGESA ComboAM5 PI 1.2.0.3g.",
        "no_rollback": False,
        "url_unverified": True,
    },
    {
        "version": "1078",
        "beta": False,
        "released": "2025-07-22",
        "size": "15.42 MB",
        "sha256": "B91B10837FEAECF1F1776C660485D0E63B045C16CD178EAFB60223B8C20935B1",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1078.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-1078.ZIP",
        "notes": "AGESA ComboAM5 PI 1.2.0.3f. Performance, stability and overclocking support.",
        "no_rollback": False,
        "url_unverified": True,
    },
    {
        "version": "0401",
        "beta": False,
        "released": "2025-06-23",
        "size": "15.39 MB",
        "sha256": "C386C8F3CF2C592EC8FCBFB0E9D8D7312A4E26E6F8F074E942A595FD4CD08140",
        "filename": "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-0401.ZIP",
        "url": DL + "TUF-GAMING-B850M-PLUS-WIFI7-W-ASUS-0401.ZIP",
        "notes": "First release.",
        "no_rollback": False,
        "url_unverified": True,
    },
]

# 1681, the newest STABLE. The only thing 1686 adds over it is TSME, a server memory-encryption
# feature irrelevant to a gaming desktop — and several versions of this BIOS cannot be rolled
# back, which makes "latest beta" a permanent decision for no gain.
RECOMMENDED = "1681"

# When the table above was last checked against the vendor page. Surfaced by the list entrypoint
# so stale pinned data announces itself rather than quietly ageing.
DATA_CHECKED = "2026-09-08"


argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="BIOS management for the ASUS TUF GAMING B850M-PLUS WIFI7 W",
            description=[
                "Lists, verifies and downloads BIOS images for ONE specific board.",
                "Deliberately narrow: ASUS sells several near-identical B850M variants whose",
                "firmware is not interchangeable, and the 'W' suffix is the whole distinction.",
                "Downloads are verified against ASUS's published SHA-256; a version with no",
                "pinned checksum is refused rather than fetched unverified.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "asus_bios_action": OptionSpec(
                    type="str",
                    required=False,
                    default="list",
                    choices=["list", "verify", "download"],
                    description=[
                        "list: report known versions. verify: check the pinned ProductID against",
                        "ASUS's live search API. download: fetch and checksum a version.",
                    ],
                ),
                "asus_bios_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description="Actually download. Default false reports the plan and stops.",
                ),
                "asus_bios_board": OptionSpec(
                    type="str",
                    required=False,
                    default=BOARD,
                    description="Exact ASUS product name. The trailing 'W' matters.",
                ),
                "asus_bios_product_id": OptionSpec(
                    type="int",
                    required=False,
                    default=PRODUCT_ID,
                    description="ASUS ProductID for this board; verified by the verify action.",
                ),
                "asus_bios_support_url": OptionSpec(
                    type="str",
                    required=False,
                    default=SUPPORT_URL,
                    description="Vendor page the pinned version table is maintained from.",
                ),
                "asus_bios_versions": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=VERSIONS,
                    description=[
                        "Pinned version table with ASUS's published SHA-256 per release.",
                        "Pinned because ASUS's BIOS API ignores the product id and returns a",
                        "hardcoded default board — see tasks/list_versions.yml.",
                    ],
                ),
                "asus_bios_recommended": OptionSpec(
                    type="str",
                    required=False,
                    default=RECOMMENDED,
                    description="Version this role recommends: the newest stable, not the newest beta.",
                ),
                "asus_bios_version": OptionSpec(
                    type="str",
                    required=False,
                    default=RECOMMENDED,
                    description="Version to download. Defaults to the recommended stable.",
                ),
                "asus_bios_allow_beta": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Permit downloading a beta release. Off by default: several versions of",
                        "this BIOS cannot be rolled back, making a beta flash permanent.",
                    ],
                ),
                "asus_bios_dest": OptionSpec(
                    type="str",
                    required=False,
                    default="/Volumes/BIOS/bios.zip",
                    description="Where to write the verified image — normally the FAT32 flash stick.",
                ),
                "asus_bios_check_live": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Fetch ASUS's support page and compare it against the pinned table.",
                        "On by default: pinned firmware data that nobody revisits looks",
                        "authoritative while quietly ageing, and a new BIOS should announce",
                        "itself. A failed fetch is reported, never treated as 'no new versions'.",
                    ],
                ),
                "asus_bios_model2_name": OptionSpec(
                    type="str",
                    required=False,
                    default="TUF-GAMING-B850M-PLUS-WIFI7-W",
                    description=[
                        "The model2Name query parameter. WITHOUT it ASUS returns a ~17KB",
                        "client-rendered shell; WITH it, the full ~566KB server-rendered page",
                        "containing every version and its SHA-256. That one parameter is the",
                        "difference between no data and all of it.",
                    ],
                ),
                "asus_bios_python": OptionSpec(
                    type="str",
                    required=False,
                    default="/usr/bin/python3",
                    description="Interpreter used for the role's page parser.",
                ),
                "asus_bios_data_checked": OptionSpec(
                    type="str",
                    required=False,
                    default=DATA_CHECKED,
                    description="Date the pinned table was last checked against the vendor page.",
                ),
                "asus_bios_stale_days": OptionSpec(
                    type="int",
                    required=False,
                    default=90,
                    description="Warn when the pinned table is older than this many days.",
                ),
            },
        ),
    }
)
