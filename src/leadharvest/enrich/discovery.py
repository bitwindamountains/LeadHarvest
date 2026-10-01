"""Find contact/about pages on the same site (blueprint section 10.5 step 4)."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from leadharvest.clean.normalize import registered_domain

_CONTACT = re.compile(r"contact|reach|get[-_ ]?in[-_ ]?touch|makipag[-_ ]?ugnayan|inquir", re.I)
_OTHER = re.compile(r"about|location|branches|find[-_ ]?us|clinic[-_ ]?hours", re.I)
_SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|zip|docx?|xlsx?|mp4|mp3)$", re.I)


def discover_contact_pages(html: str, base_url: str, limit: int = 2) -> list[str]:
    """Same-site links whose text or path looks like a contact/about page; contact first."""
    if limit <= 0:
        return []
    soup = BeautifulSoup(html, "lxml")
    site = registered_domain(base_url)
    base_clean = _strip(base_url)
    contact: list[str] = []
    other: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = _strip(urljoin(base_url, href))
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or registered_domain(url) != site:
            continue
        if url == base_clean or _SKIP_EXT.search(parts.path):
            continue
        label = f"{a.get_text(' ', strip=True)} {parts.path}"
        if _CONTACT.search(label):
            bucket = contact
        elif _OTHER.search(label):
            bucket = other
        else:
            continue
        if url not in contact and url not in other:
            bucket.append(url)
    return (contact + other)[:limit]


def _strip(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, parts.query, ""))
