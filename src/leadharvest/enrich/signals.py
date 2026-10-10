"""Website signals for agency sales (V2, F17). Pure functions over the homepage we already fetched.

Detects the site platform (WordPress, Shopify, Wix, ...), whether the page declares a mobile
viewport, and site facts (copyright year, analytics and ad pixels, online booking). Only markers
visible in the HTML and response headers are used — no extra requests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# platform → (HTML patterns, header (name, value-pattern) pairs)
_SIGNATURES: dict[str, tuple[tuple[str, ...], tuple[tuple[str, str], ...]]] = {
    "wordpress": (
        (r"/wp-content/", r"/wp-includes/", r"<meta[^>]+generator[^>]+wordpress"),
        (("link", r"api\.w\.org"), ("x-powered-by", r"wp engine")),
    ),
    "shopify": (
        (r"cdn\.shopify\.com", r"\bShopify\.theme\b"),
        (("x-shopid", r"."), ("x-shopify-stage", r"."), ("powered-by", r"shopify")),
    ),
    "wix": (
        (r"static\.wixstatic\.com", r"<meta[^>]+generator[^>]+wix\.com", r"\bwix-warmup-data\b"),
        (("x-wix-request-id", r"."),),
    ),
    "squarespace": (
        (r"static1\.squarespace\.com", r"<meta[^>]+generator[^>]+squarespace"),
        (("server", r"squarespace"),),
    ),
    "webflow": (
        (r"\bdata-wf-page\b", r"webflow\.js", r"<meta[^>]+generator[^>]+webflow"),
        (),
    ),
    "joomla": ((r"<meta[^>]+generator[^>]+joomla", r"/media/jui/"), ()),
    "drupal": (
        (r"<meta[^>]+generator[^>]+drupal", r"/sites/default/files/", r"\bdrupal-settings-json\b"),
        (("x-generator", r"drupal"), ("x-drupal-cache", r".")),
    ),
    "godaddy": ((r"img1\.wsimg\.com", r"<meta[^>]+generator[^>]+(?:go daddy|godaddy)"), ()),
    "weebly": ((r"editmysite\.com",), ()),
    "blogger": ((r"<meta[^>]+generator[^>]+blogger",), ()),
}
# Plain links to these platforms (e.g. "read our blog on blogspot") must not count, so every
# HTML marker above is an asset host, a script global, or a generator meta tag.

_VIEWPORT = re.compile(r"<meta\b[^>]*\bname\s*=\s*[\"']?viewport\b[^>]*>", re.IGNORECASE)
_WIDTH = re.compile(r"width\s*=\s*device-width", re.IGNORECASE)


def detect_tech(html: str, headers: Mapping[str, str] | None = None) -> list[str]:
    """Platforms whose markers appear in the HTML or response headers, in a stable order."""
    lower_headers = {k.lower(): v for k, v in (headers or {}).items()}
    found: list[str] = []
    for name, (html_patterns, header_patterns) in _SIGNATURES.items():
        hit = any(re.search(p, html, re.IGNORECASE) for p in html_patterns)
        if not hit:
            hit = any(
                h in lower_headers and re.search(p, lower_headers[h], re.IGNORECASE)
                for h, p in header_patterns
            )
        if hit:
            found.append(name)
    return found


def has_mobile_viewport(html: str) -> bool:
    """True if the page declares <meta name="viewport" content="width=device-width ...">."""
    return any(_WIDTH.search(tag) for tag in _VIEWPORT.findall(html))


# "© 2017", "Copyright 2015-2019", "&copy; 2012 &ndash; 2018": the last year is when it was
# touched. \u2013 is an en dash.
_COPYRIGHT = re.compile(
    r"(?:©|&copy;|&#169;|\bcopyright\b)\s*(?:\d{4}\s*(?:-|\u2013|&ndash;|to)\s*)?(\d{4})", re.I
)
# fact → HTML patterns. Script hosts and init calls only, like _SIGNATURES above.
_FACTS: dict[str, tuple[str, ...]] = {
    "analytics:google": (
        r"googletagmanager\.com/gtag/js", r"google-analytics\.com/(?:analytics|ga)\.js",
        r"googletagmanager\.com/gtm\.js",
    ),
    "pixel:meta": (r"connect\.facebook\.net/[^\"']*/fbevents\.js", r"\bfbq\(\s*['\"]init"),
    "pixel:tiktok": (r"analytics\.tiktok\.com/",),
    # Booking platforms, PH ones (SeriousMD, NowServing) included.
    "booking:calendly": (r"calendly\.com/",),
    "booking:seriousmd": (r"seriousmd\.com",),
    "booking:nowserving": (r"nowserving\.ph",),
    "booking:fresha": (r"fresha\.com/",),
    "booking:setmore": (r"setmore\.com",),
    "booking:simplybook": (r"simplybook\.(?:me|it|asia)",),
    "booking:booksy": (r"booksy\.com/",),
    "booking:acuity": (r"acuityscheduling\.com",),
    "booking:square": (r"squareup\.com/appointments", r"square\.site/book"),
}  # fmt: skip


def site_signals(html: str, current_year: int) -> list[str]:
    """Facts for sales flags: 'copyright:2017', 'analytics:google', 'pixel:meta', 'booking:…'.

    Stored as facts, not flags, so the flag rules (scoring.py) can change without refetching.
    """
    facts = [name for name, pats in _FACTS.items() if any(re.search(p, html, re.I) for p in pats)]
    years = [int(y) for y in _COPYRIGHT.findall(html) if 1990 <= int(y) <= current_year]
    if years:
        facts.insert(0, f"copyright:{max(years)}")
    return facts
