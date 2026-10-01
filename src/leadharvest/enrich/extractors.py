"""Extract emails, phones and social profiles from HTML (blueprint section 10.5). Pure functions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import phonenumbers
from bs4 import BeautifulSoup

from leadharvest.clean.normalize import (
    normalize_email,
    normalize_phones,
    normalize_url,
    registered_domain,
    social_platform,
)

JUNK_EMAIL_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "domain.com", "email.com", "yourdomain.com",
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com", "godaddy.com",
    "mysite.com", "yoursite.com", "test.com", "sentry.wixpress.com",
})  # fmt: skip
FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "yahoo.com.ph", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "ymail.com", "aol.com", "proton.me", "protonmail.com", "gmx.com",
})  # fmt: skip
PREFERRED_LOCAL_PARTS = ("info", "contact", "hello", "sales", "inquiry", "inquiries", "admin")
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
_OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*[\[\(\{]\s*at\s*[\]\)\}]\s*([A-Za-z0-9\-]+(?:\s*[\[\(\{]\s*dot\s*"
    r"[\]\)\}]\s*[A-Za-z0-9\-]+)+)",
    re.IGNORECASE,
)
_DOT_RE = re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.IGNORECASE)
_SOCIAL_EXCLUDE = re.compile(
    r"/(sharer|share|plugins|tr|dialog|intent|login|signup|hashtag|search|p|reel|explore|"
    r"watch|story\.php|photo\.php|events)(?:[/.?]|$)",
    re.IGNORECASE,
)
_JSONLD_TYPES = (
    "localbusiness",
    "organization",
    "dentist",
    "medicalbusiness",
    "store",
    "restaurant",
    "professionalservice",
    "legalservice",
    "medicalclinic",
)


@dataclass
class Extracted:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    socials: dict[str, str] = field(default_factory=dict)
    protected_emails: int = 0

    def add(self, other: Extracted) -> None:
        self.emails = list(dict.fromkeys([*self.emails, *other.emails]))
        self.phones = list(dict.fromkeys([*self.phones, *other.phones]))
        for platform, url in other.socials.items():
            self.socials.setdefault(platform, url)
        self.protected_emails += other.protected_emails


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.extract()
    return " ".join(soup.get_text(" ").split())


def _clean_email(raw: str) -> str | None:
    email = normalize_email(unquote(raw))
    if email is None:
        return None
    if email.endswith(_IMAGE_EXT) or re.search(r"@\d+x\.", email):
        return None
    domain = email.split("@", 1)[1]
    if domain in JUNK_EMAIL_DOMAINS or registered_domain(domain) in JUNK_EMAIL_DOMAINS:
        return None
    return email


def deobfuscate(text: str) -> list[str]:
    """Only bracketed forms: `name [at] domain [dot] com`, `name(at)domain(dot)com`."""
    found = []
    for local, rest in _OBFUSCATED_RE.findall(text):
        found.append(f"{local}@{_DOT_RE.sub('.', rest)}")
    return found


def _jsonld_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", type=re.compile("ld\\+json", re.IGNORECASE)):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.append(item["@graph"])
                types = item.get("@type", [])
                types = [types] if isinstance(types, str) else types
                if any(
                    str(t).lower() in _JSONLD_TYPES or str(t).lower().endswith("business")
                    for t in types
                ):
                    nodes.append(item)
    return nodes


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def extract_jsonld(soup: BeautifulSoup, region: str = "PH") -> Extracted:
    out = Extracted()
    for node in _jsonld_nodes(soup):
        for raw in _as_list(node.get("email")):
            if email := _clean_email(raw):
                out.emails.append(email)
        out.phones.extend(normalize_phones(_as_list(node.get("telephone")), region))
        for url in _as_list(node.get("sameAs")):
            platform, clean = _social(url)
            if platform:
                out.socials.setdefault(platform, clean)
    out.emails = list(dict.fromkeys(out.emails))
    out.phones = list(dict.fromkeys(out.phones))
    return out


def _social(url: str) -> tuple[str | None, str]:
    clean = normalize_url(url)
    if not clean:
        return None, ""
    platform = social_platform(clean)
    if platform in (None, "twitter") or _SOCIAL_EXCLUDE.search(urlsplit(clean).path):
        return None, ""
    path = urlsplit(clean).path.strip("/")
    if not path:
        return None, ""
    return platform, clean


def extract_socials(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        platform, clean = _social(urljoin(base_url, a["href"]))
        if platform:
            found.setdefault(platform, clean)
    return found


def extract_all(html: str, base_url: str, region: str = "PH") -> Extracted:
    """Emails (mailto → JSON-LD → text), phones (tel → JSON-LD → text), socials."""
    soup = make_soup(html)
    out = Extracted()
    out.protected_emails = len(
        soup.select('a[href*="/cdn-cgi/l/email-protection"], [data-cfemail]')
    )

    mailto = [
        a["href"][7:]
        for a in soup.find_all("a", href=True)
        if a["href"].lower().startswith("mailto:")
    ]
    tel = [
        unquote(a["href"][4:])
        for a in soup.find_all("a", href=True)
        if a["href"].lower().startswith("tel:")
    ]
    jsonld = extract_jsonld(soup, region)
    out.socials = extract_socials(soup, base_url)
    for platform, url in jsonld.socials.items():
        out.socials.setdefault(platform, url)

    text = visible_text(soup)
    emails = [*mailto, *jsonld.emails, *_EMAIL_RE.findall(text), *deobfuscate(text)]
    out.emails = list(dict.fromkeys(e for e in (_clean_email(x) for x in emails) if e))

    phones = [*normalize_phones(tel, region), *jsonld.phones]
    for match in phonenumbers.PhoneNumberMatcher(
        text, region, leniency=phonenumbers.Leniency.VALID
    ):
        phones.append(phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164))
    out.phones = list(dict.fromkeys(phones))
    return out


def text_length(html: str) -> int:
    return len(visible_text(make_soup(html)))


def rank_emails(emails: list[str], site_domain: str | None) -> list[str]:
    """Same registered domain as the site → free providers → others; prefer info@/contact@..."""

    def key(email: str) -> tuple[int, int, int]:
        local, domain = email.split("@", 1)
        reg = registered_domain(domain)
        if site_domain and reg == site_domain:
            tier = 0
        elif domain in FREE_EMAIL_DOMAINS:
            tier = 1
        else:
            tier = 2
        pref = PREFERRED_LOCAL_PARTS.index(local) if local in PREFERRED_LOCAL_PARTS else 99
        return tier, pref, emails.index(email)

    return sorted(dict.fromkeys(emails), key=key)
