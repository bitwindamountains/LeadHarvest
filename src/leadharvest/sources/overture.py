"""Overture Maps places source (docs.overturemaps.org/guides/places).

Overture publishes about 80M places a month as GeoParquet: names, addresses, phones, emails,
websites and social links, mostly from Meta (Facebook pages), Microsoft and Foursquare. It holds
no OpenStreetMap data and is licensed CDLA Permissive 2.0, Apache 2.0 or CC0 by source, so an
Overture-only list carries no ODbL share-alike.

Reads the latest release for the area's bounding box with DuckDB, keeps places inside the area's
boundary (from Nominatim), and maps them to RawBusiness. Install: `uv sync --extra overture`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from leadharvest.geo.nominatim import NominatimClient
from leadharvest.http import Sleep, request_with_retry
from leadharvest.logging_setup import get_logger
from leadharvest.models import RawBusiness, SearchQuery
from leadharvest.sources.base import SourceError

log = get_logger("overture")

STAC_CATALOG = "https://stac.overturemaps.org/catalog.json"
RELEASE_PATH = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
# Overture's own existence score (0-1). It isn't comparable across providers, so it is a coarse
# filter only. ponytail: one global threshold; tune per category after real runs.
MIN_CONFIDENCE = 0.5
_HOUSE_NUMBER = re.compile(r"^\s*(\d+[A-Za-z]?(?:-[A-Za-z0-9]+)?),?\s+(\S.*)$")

_QUERY = """
SELECT id, names.primary AS name, confidence, operating_status, websites, emails, phones,
       socials, addresses[1] AS address,
       (bbox.xmin + bbox.xmax) / 2 AS lon, (bbox.ymin + bbox.ymax) / 2 AS lat,
       [s.dataset FOR s IN sources] AS datasets
FROM read_parquet(?, hive_partitioning = true)
WHERE bbox.xmin BETWEEN ? AND ? AND bbox.ymin BETWEEN ? AND ?
  AND list_has_any(taxonomy.hierarchy, ?)
  AND names.primary IS NOT NULL
  AND coalesce(operating_status, 'open') != 'permanently_closed'
  AND coalesce(confidence, 0) >= ?
"""


def duckdb_installed() -> bool:
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return False
    return True


def default_source_names() -> list[str]:
    """Sources for a run that names none: Overture where DuckDB is installed (far more reachable
    businesses, and no ODbL share-alike on lists sold to clients: decision D6), else OSM."""
    return ["overture"] if duckdb_installed() else ["osm"]


def query_places(
    path: str, bbox: tuple[float, float, float, float], categories: Sequence[str]
) -> list[dict[str, Any]]:
    """Places in the bbox (south, west, north, east) whose taxonomy includes a category.

    Blocking (network reads for a remote path); run it in a thread.
    """
    import duckdb

    south, west, north, east = bbox
    with duckdb.connect() as con:
        if path.startswith("s3://"):
            con.execute("SET s3_region = 'us-west-2'")  # Overture's bucket; anonymous reads
        cur = con.execute(
            _QUERY, [path, west, east, south, north, list(categories), MIN_CONFIDENCE]
        )
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def _in_ring(lon: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray casting: count crossings of a ray going east from the point."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, [*ring[1:], ring[0]], strict=True):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def contains(geojson: dict[str, Any], lon: float, lat: float) -> bool:
    """Point in a GeoJSON Polygon or MultiPolygon (holes respected)."""
    if geojson.get("type") == "Polygon":
        polygons = [geojson["coordinates"]]
    elif geojson.get("type") == "MultiPolygon":
        polygons = geojson["coordinates"]
    else:
        return True  # a point or line boundary can't filter anything; keep the place
    for outer, *holes in polygons:
        if _in_ring(lon, lat, outer) and not any(_in_ring(lon, lat, h) for h in holes):
            return True
    return False


def _social(socials: Sequence[str] | None, platform: str) -> str | None:
    for url in socials or []:
        host = (urlsplit(url).hostname or "").lower()
        if host == f"{platform}.com" or host.endswith(f".{platform}.com"):
            return url
    return None


def _split_house_number(freeform: str | None) -> tuple[str | None, str | None]:
    """'717 F Roxas Blvd' → ('717', 'F Roxas Blvd'), so the street matches OSM's for dedupe."""
    match = _HOUSE_NUMBER.match(freeform or "")
    if match:
        return match.group(1), match.group(2)
    return None, freeform


def to_raw(row: dict[str, Any]) -> RawBusiness:
    address = row.get("address") or {}
    housenumber, street = _split_house_number(address.get("freeform"))
    websites = row.get("websites") or []
    return RawBusiness(
        source="overture",
        source_ref=row["id"],  # GERS id: stable across monthly releases
        name=row["name"],
        phones_raw=list(row.get("phones") or []),
        website_raw=websites[0] if websites else None,
        emails_raw=list(row.get("emails") or []),
        housenumber=housenumber,
        street=street,
        city=address.get("locality"),
        province=address.get("region"),
        facebook=_social(row.get("socials"), "facebook"),
        instagram=_social(row.get("socials"), "instagram"),
        lat=row.get("lat"),
        lon=row.get("lon"),
        payload={
            "confidence": row.get("confidence"),
            "datasets": sorted({d for d in row.get("datasets") or [] if d}),
        },
    )


class OvertureSource:
    name = "overture"

    def __init__(
        self,
        client: httpx.AsyncClient,
        geo: NominatimClient,
        *,
        path: str | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.client = client
        self.geo = geo
        self.path = path  # a local file or glob in tests; the latest release otherwise
        self._sleep = sleep
        self.last_total: int | None = None

    async def _release_path(self) -> str:
        if self.path:
            return self.path
        try:
            # Retries DNS and connection failures, 429 and 5xx: one blip shouldn't pause a run.
            response = await request_with_retry(self.client, "GET", STAC_CATALOG, sleep=self._sleep)
            response.raise_for_status()
            release = response.json()["latest"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise SourceError(f"Could not find the latest Overture release: {exc}") from exc
        return RELEASE_PATH.format(release=release)

    async def search(self, query: SearchQuery) -> list[RawBusiness]:
        if not query.overture_categories:
            raise SourceError(
                f"Category '{query.category}' has no Overture mapping. Add `overture:` "
                "categories for it in config/categories.yaml."
            )
        if not duckdb_installed():
            raise SourceError("The Overture source needs DuckDB: uv sync --extra overture")
        boundary = await self.geo.boundary(query.area)
        bbox = query.area.bbox
        if boundary and boundary.get("boundingbox"):
            south, north, west, east = (float(x) for x in boundary["boundingbox"])
            bbox = (south, west, north, east)
        if bbox is None:
            raise SourceError("The Overture source needs the area's bounding box.")
        path = await self._release_path()
        try:
            rows = await asyncio.to_thread(query_places, path, bbox, query.overture_categories)
        except Exception as exc:  # duckdb raises its own error types for I/O and SQL
            raise SourceError(f"Overture query failed: {exc}") from exc
        if boundary:
            geojson = boundary["geojson"]
            rows = [r for r in rows if contains(geojson, r["lon"], r["lat"])]
        # Most confident first, so the run's limit keeps the places most likely to exist.
        rows.sort(key=lambda r: -(r.get("confidence") or 0))
        self.last_total = len(rows)
        log.info("Overture: %d places in %s", len(rows), query.area.name)
        return [to_raw(r) for r in rows[: query.fetch_n]]
