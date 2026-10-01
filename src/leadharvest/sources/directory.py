"""YAML-driven scraper for a public business directory (V1, F3; blueprint workflow W4).

Every page goes through the PoliteFetcher (robots.txt, SSRF guard, per-host delay), and a
config only loads if its section-13 scraping checklist is fully confirmed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import yaml
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from leadharvest.clean.normalize import registered_domain
from leadharvest.enrich.fetcher import FetchError, PoliteFetcher
from leadharvest.logging_setup import get_logger
from leadharvest.models import RawBusiness, SearchQuery
from leadharvest.sources.base import SourceError

log = get_logger("directory")

FIELD_NAMES = (
    "name", "phone", "website", "email", "address", "street", "housenumber", "suburb", "city",
    "province", "facebook", "instagram", "opening_hours", "detail_url", "lat", "lon",
)  # fmt: skip
MAX_PAGES_LIMIT = 50


class DirectoryConfigError(Exception):
    pass


class FieldSpec(BaseModel):
    selector: str
    attr: str | None = None  # None → element text
    multiple: bool = False


class Checklist(BaseModel):
    robots_allows: bool = False
    tos_allows: bool = False
    public_no_login: bool = False
    rate_ok: bool = False
    user_agent_ok: bool = False


class DirectoryConfig(BaseModel):
    name: str
    label: str = ""
    base_url: str
    checklist: Checklist
    start_urls: list[str] = Field(min_length=1)
    category_map: dict[str, str] = Field(default_factory=dict)
    item: str
    fields: dict[str, FieldSpec]
    next_page: FieldSpec | None = None
    max_pages: int = Field(default=5, ge=1, le=MAX_PAGES_LIMIT)

    @field_validator("fields", mode="before")
    @classmethod
    def _shorthand(cls, value: dict[str, Any]) -> dict[str, Any]:
        """`name: ".title"` is shorthand for `name: {selector: ".title"}`."""
        return {k: ({"selector": v} if isinstance(v, str) else v) for k, v in value.items()}

    @field_validator("next_page", mode="before")
    @classmethod
    def _next_shorthand(cls, value: Any) -> Any:
        return {"selector": value, "attr": "href"} if isinstance(value, str) else value

    @model_validator(mode="after")
    def _checks(self) -> DirectoryConfig:
        unknown = set(self.fields) - set(FIELD_NAMES)
        if unknown:
            raise ValueError(f"unknown fields {sorted(unknown)}; allowed: {', '.join(FIELD_NAMES)}")
        if "name" not in self.fields:
            raise ValueError("fields.name is required")
        missing = [k for k, ok in self.checklist.model_dump().items() if not ok]
        if missing:
            raise ValueError(
                "scraping checklist not confirmed: "
                + ", ".join(missing)
                + " (blueprint section 13). Only scrape sites that allow it."
            )
        site = site_key(self.base_url)
        if not site:
            raise ValueError(f"base_url {self.base_url!r} is not a valid http(s) URL")
        for url in self.start_urls:
            if site_key(url.split("{", 1)[0]) != site:
                raise ValueError(f"start URL {url} is not on {site}")
        return self


def site_key(url: str) -> str | None:
    """Registered domain, or the bare hostname when there is no known public suffix.

    Never None for two different hosts, so `site_key(a) == site_key(b)` is a safe check.
    """
    host = urlsplit(url).hostname if "://" in url else None
    if not host:
        return None
    return registered_domain(host) or host.lower()


def default_directories_dir() -> Path:
    cwd = Path("config/directories")
    if cwd.is_dir():
        return cwd
    return Path(__file__).resolve().parents[3] / "config" / "directories"


def available_directories(folder: Path | None = None) -> list[str]:
    folder = folder or default_directories_dir()
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.yaml") if not p.stem.startswith("_"))


def load_directory_config(name: str, folder: Path | None = None) -> DirectoryConfig:
    folder = folder or default_directories_dir()
    path = folder / f"{name}.yaml"
    if name.startswith("_") or not path.is_file():
        options = ", ".join(available_directories(folder)) or "none configured"
        raise DirectoryConfigError(f"No directory adapter '{name}' (available: {options}).")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return DirectoryConfig.model_validate({"name": name, **data})
    except (yaml.YAMLError, ValidationError) as exc:
        raise DirectoryConfigError(f"Invalid adapter {path}: {exc}") from None


def _extract(item: Tag, spec: FieldSpec, base_url: str) -> str | None:
    nodes = item.select(spec.selector) if spec.multiple else [item.select_one(spec.selector)]
    values = []
    for node in nodes:
        if node is None:
            continue
        raw = node.get(spec.attr) if spec.attr else node.get_text(" ", strip=True)
        if isinstance(raw, list):
            raw = " ".join(raw)
        if raw:
            value = str(raw).strip()
            if spec.attr in ("href", "src"):
                value = urljoin(base_url, value)
            values.append(value)
    if not values:
        return None
    return "; ".join(values) if spec.multiple else values[0]


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def parse_listing(html: str, config: DirectoryConfig, page_url: str) -> list[RawBusiness]:
    soup = BeautifulSoup(html, "lxml")
    records: list[RawBusiness] = []
    for item in soup.select(config.item):
        values = {k: _extract(item, spec, page_url) for k, spec in config.fields.items()}
        name = values.get("name")
        if not name:
            continue
        detail = values.get("detail_url")
        if detail:
            ref = detail
        else:
            key = f"{name}|{values.get('address') or values.get('street') or ''}".lower()
            ref = "h:" + hashlib.sha1(key.encode()).hexdigest()[:16]
        email = values.get("email")
        if email and email.lower().startswith("mailto:"):
            email = email[7:]
        phone = values.get("phone")
        if phone and phone.lower().startswith("tel:"):
            phone = phone[4:]
        records.append(
            RawBusiness(
                source=f"directory:{config.name}",
                source_ref=ref,
                name=name,
                phones_raw=[phone] if phone else [],
                website_raw=values.get("website"),
                emails_raw=[email] if email else [],
                housenumber=values.get("housenumber"),
                street=values.get("street") or values.get("address"),
                suburb=values.get("suburb"),
                city=values.get("city"),
                province=values.get("province"),
                facebook=values.get("facebook"),
                instagram=values.get("instagram"),
                opening_hours=values.get("opening_hours"),
                lat=_float(values.get("lat")),
                lon=_float(values.get("lon")),
                payload={"page": page_url, **{k: v for k, v in values.items() if v}},
            )
        )
    return records


def next_page_url(html: str, config: DirectoryConfig, page_url: str) -> str | None:
    if config.next_page is None:
        return None
    soup = BeautifulSoup(html, "lxml")
    url = _extract(soup, config.next_page, page_url)
    if not url or site_key(url) != site_key(config.base_url):
        return None
    return url


class DirectorySource:
    def __init__(self, config: DirectoryConfig, fetcher: PoliteFetcher) -> None:
        self.config = config
        self.fetcher = fetcher
        self.name = f"directory:{config.name}"
        self.pages_fetched = 0

    def start_urls(self, query: SearchQuery) -> list[str]:
        category = self.config.category_map.get(query.category, query.category)
        values = {
            "category": quote(category),
            "city": quote(query.area.name),
            "location": quote(query.location),
        }
        return [url.format(**values) for url in self.config.start_urls]

    async def search(
        self, query: SearchQuery, *, max_pages: int | None = None
    ) -> list[RawBusiness]:
        pages = min(max_pages or self.config.max_pages, self.config.max_pages)
        records: dict[str, RawBusiness] = {}
        for start in self.start_urls(query):
            url: str | None = start
            seen: set[str] = set()
            for _ in range(pages):
                if url is None or url in seen:
                    break
                seen.add(url)
                try:
                    page = await self.fetcher.get_page(url)
                except FetchError as exc:
                    if not records and self.pages_fetched == 0:
                        raise SourceError(f"{self.name}: cannot fetch {url} ({exc})") from exc
                    log.warning("%s: stopping at %s (%s)", self.name, url, exc)
                    break
                self.pages_fetched += 1
                for record in parse_listing(page.text, self.config, page.final_url):
                    records.setdefault(record.source_ref, record)
                if len(records) >= query.fetch_n:
                    return list(records.values())[: query.fetch_n]
                url = next_page_url(page.text, self.config, page.final_url)
        return list(records.values())
