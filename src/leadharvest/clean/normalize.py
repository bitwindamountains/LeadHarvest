"""Normalization rules (blueprint section 10.3). Pure functions."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import phonenumbers
import tldextract

# Offline: use the bundled public-suffix snapshot, never download at runtime.
_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

SHARED_HOST_DOMAINS = frozenset({
    "wixsite.com", "wix.com", "blogspot.com", "wordpress.com", "business.site", "weebly.com",
    "square.site", "godaddysites.com", "webnode.page", "webnode.com", "carrd.co", "linktr.ee",
    "google.com", "github.io", "netlify.app", "vercel.app", "myshopify.com", "jimdosite.com",
    "strikingly.com", "mystrikingly.com", "site123.me", "yolasite.com", "tumblr.com",
    "facebook.com", "instagram.com", "tiktok.com", "linkedin.com",
})  # fmt: skip

SOCIAL_HOSTS = {
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "instagram": ("instagram.com",),
    "tiktok": ("tiktok.com",),
    "linkedin": ("linkedin.com",),
    "twitter": ("twitter.com", "x.com"),
}

_TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "igshid"}
_LEGAL_SUFFIXES = {"inc", "corp", "corporation", "co", "ltd", "opc", "incorporated", "llc"}
_STREET_ABBREV = {
    "st": "street", "str": "street", "ave": "avenue", "av": "avenue", "blvd": "boulevard",
    "rd": "road", "dr": "drive", "hwy": "highway", "ext": "extension", "cor": "corner",
    "brgy": "barangay", "bgy": "barangay",
}  # fmt: skip
_UNIT_PATTERN = re.compile(
    r"\b(?:unit|rm|room|suite|ste|flr|floor|level|lvl|bldg|building|stall|space)\s*[#.]?\s*[\w-]*"
    r"|\b\d+(?:st|nd|rd|th)\s+(?:floor|flr|level)\b"
    r"|\b\d+/f\b|#\s*[\w-]+",
    re.IGNORECASE,
)
_CITY_AFFIX = re.compile(r"^(?:city|municipality) of\s+|\s+city$", re.IGNORECASE)


# ---- phones ---------------------------------------------------------------------------------


def _parse_valid(text: str, region: str) -> phonenumbers.PhoneNumber | None:
    try:
        number = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        return None
    return number if phonenumbers.is_valid_number(number) else None


def _e164(number: phonenumbers.PhoneNumber) -> str:
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_phones(raw_values: list[str] | str | None, region: str = "PH") -> list[str]:
    """Split and parse raw phone strings into unique, valid E.164 numbers.

    Handles PH shorthands: `(02) 8123-4567/68` (last digits replaced) and a second local
    number without an area code (`(02) 8123-4567 / 8765-4321`).
    """
    if not raw_values:
        return []
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    out: list[str] = []
    for raw in raw_values:
        for group in re.split(r"[;,\n]", raw or ""):
            prev: phonenumbers.PhoneNumber | None = None
            for part in group.split("/"):
                part = part.strip()
                digits = re.sub(r"\D", "", part)
                if not digits:
                    continue
                number = None
                if prev is not None and len(digits) <= 4 and not re.search(r"[A-Za-z]", part):
                    base = _e164(prev)
                    number = _parse_valid(base[: -len(digits)] + digits, region)
                else:
                    number = _parse_valid(part, region)
                    if number is None and prev is not None:
                        number = _with_area_code(prev, digits, region)
                if number is not None:
                    e164 = _e164(number)
                    if e164 not in out:
                        out.append(e164)
                    prev = number
    return out


def _with_area_code(
    prev: phonenumbers.PhoneNumber, digits: str, region: str
) -> phonenumbers.PhoneNumber | None:
    ac_len = phonenumbers.length_of_geographical_area_code(prev)
    if ac_len <= 0:
        return None
    area_code = str(prev.national_number)[:ac_len]
    return _parse_valid(f"+{prev.country_code}{area_code}{digits}", region)


# ---- URLs and domains -----------------------------------------------------------------------


def social_platform(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    for platform, hosts in SOCIAL_HOSTS.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return platform
    return None


def normalize_url(raw: str | None) -> str | None:
    """Clean a URL; returns None for anything that isn't a usable http(s) URL."""
    if not raw:
        return None
    text = raw.strip().strip("<>\"'")
    if not text or " " in text:
        return None
    if text.startswith("//"):
        text = "https:" + text
    elif "://" not in text:
        if text.lower().startswith(("mailto:", "tel:", "javascript:")):
            return None
        text = "https://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if scheme not in ("http", "https") or not host or "." not in host:
        return None
    netloc = host if port is None else f"{host}:{port}"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    path = (parts.path or "").rstrip("/")
    if query and not path:
        path = "/"
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def split_website(raw: str | None) -> tuple[str | None, dict[str, str]]:
    """Normalize a 'website' value; social profile URLs are moved to their own field."""
    url = normalize_url(raw)
    if url is None:
        return None, {}
    platform = social_platform(url)
    if platform is None:
        return url, {}
    if platform == "twitter":
        return None, {}
    return None, {platform: url}


def registered_domain(url_or_host: str | None) -> str | None:
    if not url_or_host:
        return None
    host = urlsplit(url_or_host).hostname if "://" in url_or_host else url_or_host
    if not host:
        return None
    ext = _tld(host.lower())
    if not ext.domain or not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}"


def is_shared_domain(domain: str | None) -> bool:
    return bool(domain) and domain in SHARED_HOST_DOMAINS


# ---- names, streets, cities -----------------------------------------------------------------


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^\w]+", " ", text.replace("&", " and ")).replace("_", " ").split()


def name_key(name: str) -> str:
    tokens = _tokens(_fold(name))
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def street_key(street: str | None) -> str | None:
    if not street:
        return None
    text = _UNIT_PATTERN.sub(" ", _fold(street))
    tokens = [_STREET_ABBREV.get(t, t) for t in _tokens(text)]
    key = " ".join(tokens)
    return key or None


def city_key(city: str | None) -> str | None:
    if not city:
        return None
    text = _CITY_AFFIX.sub("", _fold(city).strip())
    key = " ".join(_tokens(text))
    return key or None


def normalize_email(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip().removeprefix("mailto:").split("?", 1)[0].strip().lower()
    if re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", text):
        return text
    return None


def format_address(*parts: str | None) -> str | None:
    cleaned = [p.strip() for p in parts if p and p.strip()]
    joined = ", ".join(dict.fromkeys(cleaned))
    return joined or None
