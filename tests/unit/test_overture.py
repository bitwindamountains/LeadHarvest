"""Overture places source: the real DuckDB query over a synthetic GeoParquet, boundary filter."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from leadharvest.exporters.base import (
    OSM_ATTRIBUTION,
    OVERTURE_ATTRIBUTION,
    attribution,
    sources_attribution,
)
from leadharvest.geo.nominatim import NominatimClient
from leadharvest.http import MinIntervalLimiter, make_client
from leadharvest.models import ResolvedArea, Run, SearchQuery, utcnow_iso
from leadharvest.sources.base import SourceError
from leadharvest.sources.overture import (
    OvertureSource,
    _split_house_number,
    contains,
    query_places,
    to_raw,
)

duckdb = pytest.importorskip("duckdb")

DENTAL = ["health_care", "outpatient_care_facility", "dental_clinic"]
# A square "city" from (121.00, 14.50) to (121.10, 14.60) with a hole in one corner.
SQUARE = [[121.0, 14.5], [121.1, 14.5], [121.1, 14.6], [121.0, 14.6], [121.0, 14.5]]
HOLE = [[121.0, 14.5], [121.02, 14.5], [121.02, 14.52], [121.0, 14.52], [121.0, 14.5]]
BOUNDARY = {
    "geojson": {"type": "Polygon", "coordinates": [SQUARE]},
    "boundingbox": ["14.5", "14.6", "121.0", "121.1"],  # Nominatim order: s, n, w, e
}
AREA = ResolvedArea(kind="area", area_id=3_600_000_000 + 1520040, name="Makati")


def _place(pid: str, name: str | None, lon: float, lat: float, **kw: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "names": {"primary": name},
        "confidence": kw.get("confidence", 0.9),
        "operating_status": kw.get("status"),
        "websites": kw.get("websites"),
        "emails": kw.get("emails"),
        "phones": kw.get("phones"),
        "socials": kw.get("socials"),
        "addresses": kw.get("addresses"),
        "bbox": {"xmin": lon, "xmax": lon, "ymin": lat, "ymax": lat},
        "taxonomy": {
            "primary": kw.get("hierarchy", DENTAL)[-1],
            "hierarchy": kw.get("hierarchy", DENTAL),
        },
        "sources": [{"dataset": "meta"}],
    }


PLACES = [
    _place("smile", "Smile Dental", 121.05, 14.55, confidence=0.8,
           websites=["https://smile.ph"], emails=["info@smile.ph"], phones=["+639171234567"],
           socials=["https://www.facebook.com/smile", "https://instagram.com/smileph"],
           addresses=[{"freeform": "1 Ayala Ave", "locality": "Makati", "region": "NCR"}]),
    _place("ortho", "Bright Ortho", 121.06, 14.56, confidence=0.95,
           hierarchy=[*DENTAL, "orthodontics"]),  # a subcategory still matches
    _place("unsure", "Maybe Dental", 121.05, 14.57, confidence=0.3),  # below the floor
    _place("closed", "Old Dental", 121.05, 14.58, status="permanently_closed"),
    _place("cafe", "Kape", 121.05, 14.55, hierarchy=["food_and_drink", "cafe"]),
    _place("nameless", None, 121.05, 14.55),
    _place("hole", "Corner Dental", 121.01, 14.51),  # inside the bbox, in the boundary's hole
    _place("far", "Cebu Dental", 123.9, 10.3),  # outside the bbox
]  # fmt: skip


@pytest.fixture
def places_file(tmp_path) -> str:
    path = tmp_path / "places.parquet"
    con = duckdb.connect()
    con.execute("""CREATE TABLE p (
        id VARCHAR, names STRUCT("primary" VARCHAR), confidence DOUBLE, operating_status VARCHAR,
        websites VARCHAR[], emails VARCHAR[], phones VARCHAR[], socials VARCHAR[],
        addresses STRUCT(freeform VARCHAR, locality VARCHAR, region VARCHAR)[],
        bbox STRUCT(xmin DOUBLE, xmax DOUBLE, ymin DOUBLE, ymax DOUBLE),
        taxonomy STRUCT("primary" VARCHAR, hierarchy VARCHAR[]), sources STRUCT(dataset VARCHAR)[]
    )""")
    columns = list(PLACES[0])
    con.executemany(
        f"INSERT INTO p VALUES ({', '.join('?' for _ in columns)})",
        [[p[c] for c in columns] for p in PLACES],
    )
    con.execute(f"COPY p TO '{path.as_posix()}' (FORMAT parquet)")
    con.close()
    return path.as_posix()


def test_contains_polygon_hole_and_multipolygon() -> None:
    poly = {"type": "Polygon", "coordinates": [SQUARE, HOLE]}
    assert contains(poly, 121.05, 14.55)
    assert not contains(poly, 121.01, 14.51)  # in the hole
    assert not contains(poly, 121.2, 14.55)
    multi = {"type": "MultiPolygon", "coordinates": [[HOLE], [SQUARE]]}
    assert contains(multi, 121.01, 14.51)
    assert contains({"type": "Point", "coordinates": [0, 0]}, 5, 5)  # can't filter: keep


def test_query_places_filters_category_confidence_status(places_file) -> None:
    rows = query_places(places_file, (14.5, 121.0, 14.6, 121.1), ["dental_clinic"])
    assert {r["id"] for r in rows} == {"smile", "ortho", "hole"}
    raw = to_raw(next(r for r in rows if r["id"] == "smile"))
    assert (raw.source, raw.source_ref, raw.name) == ("overture", "smile", "Smile Dental")
    assert raw.phones_raw == ["+639171234567"] and raw.emails_raw == ["info@smile.ph"]
    assert raw.website_raw == "https://smile.ph"
    assert raw.facebook == "https://www.facebook.com/smile"
    assert raw.instagram == "https://instagram.com/smileph"
    assert (raw.housenumber, raw.street, raw.city) == ("1", "Ayala Ave", "Makati")
    assert raw.province == "NCR"
    assert (raw.lon, raw.lat) == (121.05, 14.55)
    assert raw.payload == {"confidence": 0.8, "datasets": ["meta"]}


class FakeGeo:
    def __init__(self, boundary: dict[str, Any] | None) -> None:
        self._boundary = boundary

    async def boundary(self, area: ResolvedArea) -> dict[str, Any] | None:
        return self._boundary


def _query(limit: int = 100, overture: list[str] | None = None) -> SearchQuery:
    return SearchQuery(
        category="dentist", osm_tags=["amenity=dentist"], location="Makati", area=AREA,
        limit=limit, overture_categories=["dental_clinic"] if overture is None else overture,
    )  # fmt: skip


async def test_source_keeps_boundary_sorts_by_confidence_and_limits(places_file) -> None:
    hole = {**BOUNDARY, "geojson": {"type": "Polygon", "coordinates": [SQUARE, HOLE]}}
    async with httpx.AsyncClient() as client:
        source = OvertureSource(client, FakeGeo(hole), path=places_file)  # type: ignore[arg-type]
        records = await source.search(_query())
        assert [r.source_ref for r in records] == ["ortho", "smile"]  # "hole" dropped
        assert source.last_total == 2
        one = await source.search(_query(limit=1))  # fetch_n = 2: ceil(1 * 1.5)
        assert len(one) == 2
        with pytest.raises(SourceError, match="no Overture mapping"):
            await source.search(_query(overture=[]))


async def test_source_uses_area_bbox_without_boundary(places_file) -> None:
    area = ResolvedArea(kind="bbox", bbox=(14.5, 121.0, 14.6, 121.1), name="Makati")
    async with httpx.AsyncClient() as client:
        source = OvertureSource(client, FakeGeo(None), path=places_file)  # type: ignore[arg-type]
        records = await source.search(_query().model_copy(update={"area": area}))
    assert {r.source_ref for r in records} == {"ortho", "smile", "hole"}


@respx.mock
async def test_source_finds_latest_release() -> None:
    respx.get("https://stac.overturemaps.org/catalog.json").respond(json={"latest": "2026-09-23.1"})
    async with httpx.AsyncClient() as client:
        path = await OvertureSource(client, FakeGeo(None))._release_path()  # type: ignore[arg-type]
    assert path == ("s3://overturemaps-us-west-2/release/2026-09-23.1/theme=places/type=place/*")


@respx.mock
async def test_release_lookup_rides_out_a_dns_blip() -> None:
    dns = httpx.ConnectError("[Errno 11001] getaddrinfo failed")
    route = respx.get("https://stac.overturemaps.org/catalog.json")
    route.side_effect = [dns, httpx.Response(200, json={"latest": "2026-09-23.1"})]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    async with httpx.AsyncClient() as client:
        source = OvertureSource(client, FakeGeo(None), sleep=sleep)  # type: ignore[arg-type]
        assert "2026-09-23.1" in await source._release_path()
        assert route.call_count == 2 and waits == [1.0]
        route.side_effect = [dns, dns, dns]  # still down after three tries: a clear error
        with pytest.raises(SourceError, match=r"latest Overture release.*getaddrinfo"):
            await source._release_path()


@respx.mock
async def test_nominatim_boundary_looks_up_by_osm_id_and_caches(settings, repo) -> None:
    route = respx.get("https://nominatim.test/lookup").respond(
        json=[{"osm_id": 1520040, **BOUNDARY}]
    )
    async with make_client(settings) as client:
        geo = NominatimClient(settings, client, repo, limiter=MinIntervalLimiter(0))
        assert await geo.boundary(AREA) == BOUNDARY
        assert await geo.boundary(AREA) == BOUNDARY  # cached: no second request
        assert await geo.boundary(ResolvedArea(kind="bbox", bbox=(1, 2, 3, 4), name="x")) is None
    assert route.call_count == 1
    params = parse_qs(str(route.calls[0].request.url.query, "ascii"))
    assert params["osm_ids"] == ["R1520040"] and params["polygon_geojson"] == ["1"]


def test_attribution_follows_sources() -> None:
    def run(*sources: str) -> Run:
        return Run(id="r", category="dentist", location="Makati", created_at=utcnow_iso(),
                   sources=list(sources))  # fmt: skip

    assert attribution(run("osm"), []) == OSM_ATTRIBUTION
    assert attribution(run("overture"), []) == OVERTURE_ATTRIBUTION
    assert attribution(run("osm", "overture"), []).splitlines() == [
        OSM_ATTRIBUTION, OVERTURE_ATTRIBUTION]  # fmt: skip
    assert sources_attribution({"overture"}) == OVERTURE_ATTRIBUTION  # the search page's default
    assert sources_attribution(set()) == OSM_ATTRIBUTION
    assert attribution(run("directory:x"), []) == OSM_ATTRIBUTION  # as before


def test_pipeline_and_cli_know_the_overture_source(settings, repo) -> None:
    from leadharvest.cli import _parse_sources
    from leadharvest.pipeline import default_sources

    run = Run(id="r", category="dentist", location="Makati", created_at=utcnow_iso(),
              sources=["osm", "overture"])  # fmt: skip
    built = default_sources(settings, repo)(httpx.AsyncClient(), run, None)  # type: ignore[arg-type]
    assert [s.name for s in built] == ["osm", "overture"]
    assert _parse_sources("overture, osm") == ["overture", "osm"]


def test_split_house_number_for_street_matching() -> None:
    assert _split_house_number("717 F Roxas Blvd") == ("717", "F Roxas Blvd")
    assert _split_house_number("12-B, Jupiter St") == ("12-B", "Jupiter St")
    assert _split_house_number("1st Ave cor. 5th St") == (None, "1st Ave cor. 5th St")
    assert _split_house_number("Unit 5 Ayala Tower") == (None, "Unit 5 Ayala Tower")
    assert _split_house_number(None) == (None, None)
