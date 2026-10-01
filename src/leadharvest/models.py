"""Typed records passed between pipeline steps (blueprint section 9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal["running", "completed", "partial", "failed"]
Step = Literal["search", "clean", "enrich", "score", "export", "done"]
STEPS: tuple[Step, ...] = ("search", "clean", "enrich", "score", "export", "done")

EnrichStatus = Literal[
    "pending", "ok", "no_website", "robots_blocked", "timeout", "http_error", "failed"
]


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run_id() -> str:
    return str(uuid.uuid4())


def new_lead_id() -> str:
    return "L-" + uuid.uuid4().hex[:12]


class ResolvedArea(BaseModel):
    kind: Literal["area", "bbox"]
    area_id: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # south, west, north, east
    name: str
    display_name: str = ""


class SearchQuery(BaseModel):
    category: str
    osm_tags: list[str]
    location: str
    area: ResolvedArea
    limit: int = 200

    @property
    def fetch_n(self) -> int:
        return -(-self.limit * 3 // 2)  # ceil(limit * 1.5)


class RawBusiness(BaseModel):
    source: str
    source_ref: str
    name: str
    phones_raw: list[str] = Field(default_factory=list)
    website_raw: str | None = None
    emails_raw: list[str] = Field(default_factory=list)
    housenumber: str | None = None
    street: str | None = None
    suburb: str | None = None
    city: str | None = None
    province: str | None = None
    facebook: str | None = None
    instagram: str | None = None
    opening_hours: str | None = None
    lat: float | None = None
    lon: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Lead(BaseModel):
    lead_id: str | None = None
    business_name: str
    name_key: str
    categories: list[str] = Field(default_factory=list)
    address: str | None = None
    city: str | None = None
    city_key: str | None = None
    city_source: Literal["osm", "run_area"] | None = None
    province: str | None = None
    street_key: str | None = None
    country: str = "PH"
    lat: float | None = None
    lon: float | None = None
    phone: str | None = None
    phones_extra: list[str] = Field(default_factory=list)
    email: str | None = None
    emails_extra: list[str] = Field(default_factory=list)
    website: str | None = None
    final_url: str | None = None
    https_ok: bool | None = None
    tech: list[str] = Field(default_factory=list)  # site platform(s), e.g. ["wordpress"]
    mobile_viewport: bool | None = None
    domain: str | None = None
    facebook: str | None = None
    instagram: str | None = None
    linkedin: str | None = None
    tiktok: str | None = None
    opening_hours: str | None = None
    sources: list[str] = Field(default_factory=list)
    enrich_status: EnrichStatus = "pending"
    enriched_at: str | None = None
    enrich_error: str | None = None
    score: int | None = None
    flags: list[str] = Field(default_factory=list)
    first_seen_run_id: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    updated_at: str | None = None

    # Not stored on the lead: identity of the raw record this candidate came from.
    source: str | None = Field(default=None, exclude=True)
    source_ref: str | None = Field(default=None, exclude=True)


class Run(BaseModel):
    id: str
    category: str
    location: str
    area_id: int | None = None
    area_kind: Literal["area", "bbox"] | None = None
    bbox: tuple[float, float, float, float] | None = None
    area_name: str | None = None
    sources: list[str] = Field(default_factory=lambda: ["osm"])
    limit_n: int = 200
    export_targets: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)  # e.g. {"js": True, "mx": True}
    status: RunStatus = "running"
    current_step: Step = "search"
    stats: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: str
    finished_at: str | None = None

    def resolved_area(self) -> ResolvedArea | None:
        if self.area_kind is None:
            return None
        return ResolvedArea(
            kind=self.area_kind,
            area_id=self.area_id,
            bbox=self.bbox,
            name=self.area_name or self.location,
        )


class ExportResult(BaseModel):
    exporter: str
    target: str
    rows_updated: int = 0
    rows_appended: int = 0

    @property
    def rows_written(self) -> int:
        return self.rows_updated + self.rows_appended
