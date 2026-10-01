import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from leadharvest.categories import UnknownCategory, load_categories, resolve_category
from leadharvest.geo.nominatim import LocationNotFound, NominatimClient, resolve_result
from leadharvest.http import MinIntervalLimiter, make_client
from leadharvest.models import ResolvedArea, SearchQuery
from leadharvest.sources.base import SourceError
from leadharvest.sources.osm_overpass import (
    OsmOverpassSource,
    OverpassClient,
    build_query,
    parse_count,
    parse_elements,
)
from tests.conftest import read_fixture

AREA = ResolvedArea(kind="area", area_id=3601520040, name="Makati")


def test_build_query_area_and_bbox() -> None:
    q = build_query(AREA, ["amenity=dentist", "healthcare=dentist"], out="center tags 300")
    assert "area(id:3601520040)->.searchArea;" in q
    assert 'nwr["amenity"="dentist"](area.searchArea);' in q
    assert q.endswith("out center tags 300;")
    bbox = ResolvedArea(kind="bbox", bbox=(14.5, 121.0, 14.6, 121.1), name="x")
    q2 = build_query(bbox, ['name="evil"'], out="count")
    assert "area(" not in q2
    assert "(14.5,121.0,14.6,121.1)" in q2
    assert '\\"evil\\"' in q2  # tag values are escaped


def test_parse_elements_maps_tags_and_skips_unnamed() -> None:
    records = parse_elements(json.loads(read_fixture("overpass", "makati_dentists.json")))
    assert [r.source_ref for r in records] == ["node/1001", "way/2002", "node/1003", "node/1005"]
    first = records[0]
    assert first.phones_raw == ["0917 123 4567; (02) 8123-4567"]
    assert first.city == "Makati City" and first.street == "Ayala Ave."
    assert first.facebook == "https://www.facebook.com/SmileClinicPH"
    assert records[1].lat == 14.5551  # way center
    assert records[3].website_raw == "brightsmile.ph"


def test_parse_count() -> None:
    assert parse_count(json.loads(read_fixture("overpass", "count.json"))) == 5
    assert parse_count({"elements": []}) == 0


async def _noop_sleep(_: float) -> None:
    return None


@respx.mock
async def test_overpass_source_counts_then_fetches_with_buffer(settings) -> None:
    route = respx.post("https://overpass.test/api/interpreter").mock(side_effect=[
        httpx.Response(200, text=read_fixture("overpass", "count.json")),
        httpx.Response(200, text=read_fixture("overpass", "makati_dentists.json")),
    ])  # fmt: skip
    async with make_client(settings) as client:
        source = OsmOverpassSource(OverpassClient(settings, client, sleep=_noop_sleep))
        query = SearchQuery(
            category="dentist", osm_tags=["amenity=dentist"], location="Makati", area=AREA, limit=4
        )
        records = await source.search(query)
    assert len(records) == 4
    assert source.last_total == 5
    sent = parse_qs(route.calls[1].request.content.decode())["data"][0]
    assert sent.endswith("out center tags 6;")  # ceil(4 * 1.5)
    assert parse_qs(route.calls[0].request.content.decode())["data"][0].endswith("out count;")


@respx.mock
async def test_overpass_falls_back_to_second_url(settings) -> None:
    respx.post("https://overpass.test/api/interpreter").respond(504)
    second = respx.post("https://overpass2.test/api/interpreter").respond(
        200, text=read_fixture("overpass", "count.json")
    )
    async with make_client(settings) as client:
        oc = OverpassClient(settings, client, sleep=_noop_sleep, base_delay=0)
        data = await oc.query("[out:json];out count;")
    assert parse_count(data) == 5
    assert second.called


@respx.mock
async def test_overpass_all_endpoints_fail_raises_source_error(settings) -> None:
    respx.post("https://overpass.test/api/interpreter").respond(429, headers={"Retry-After": "1"})
    respx.post("https://overpass2.test/api/interpreter").mock(side_effect=httpx.ConnectError("x"))
    async with make_client(settings) as client:
        oc = OverpassClient(settings, client, sleep=_noop_sleep, base_delay=0)
        with pytest.raises(SourceError):
            await oc.query("q")


@respx.mock
async def test_overpass_runtime_remark_is_an_error(settings) -> None:
    respx.post("https://overpass.test/api/interpreter").respond(
        200, json={"elements": [], "remark": "runtime error: Query timed out"}
    )
    respx.post("https://overpass2.test/api/interpreter").respond(
        200, text=read_fixture("overpass", "count.json")
    )
    async with make_client(settings) as client:
        oc = OverpassClient(settings, client, sleep=_noop_sleep, base_delay=0)
        assert parse_count(await oc.query("q")) == 5


def test_resolve_result_relation_way_and_bbox() -> None:
    makati = json.loads(read_fixture("nominatim", "makati.json"))
    area = resolve_result(makati[0])
    assert area.kind == "area" and area.area_id == 3_600_000_000 + 1520040
    assert area.name == "Makati"
    way = resolve_result(json.loads(read_fixture("nominatim", "bgc_way.json"))[0])
    assert way.area_id == 2_400_000_000 + 45678
    assert way.bbox == (14.5380, 121.0400, 14.5640, 121.0590)  # south, west, north, east
    node = resolve_result(makati[1])
    assert node.kind == "bbox" and node.bbox == (14.56, 121.03, 14.57, 121.04)


@respx.mock
async def test_nominatim_resolve_caches_and_restricts_country(settings, repo, clock) -> None:
    route = respx.get("https://nominatim.test/search").respond(
        200, text=read_fixture("nominatim", "makati.json")
    )
    async with make_client(settings) as client:
        geo = NominatimClient(
            settings, client, repo, limiter=MinIntervalLimiter(1.0, clock=clock, sleep=clock.sleep)
        )
        area, others = await geo.resolve("Makati, Philippines")
        again, _ = await geo.resolve("makati,  philippines".replace(",  ", ", "))
    assert area == again
    assert others == ["Poblacion, Makati, Metro Manila, Philippines"]
    assert route.call_count == 1
    assert route.calls[0].request.url.params["countrycodes"] == "ph"


@respx.mock
async def test_nominatim_not_found(settings, repo, clock) -> None:
    respx.get("https://nominatim.test/search").respond(200, json=[])
    async with make_client(settings) as client:
        geo = NominatimClient(
            settings, client, repo, limiter=MinIntervalLimiter(1.0, clock=clock, sleep=clock.sleep)
        )
        with pytest.raises(LocationNotFound):
            await geo.resolve("Nowhereville")


def test_categories_load_and_resolve() -> None:
    cats = load_categories()
    assert cats["dentist"].osm_tags == ["amenity=dentist", "healthcare=dentist"]
    assert resolve_category("Dentist", cats).key == "dentist"
    assert resolve_category("dental clinic", cats).key == "dentist"
    with pytest.raises(UnknownCategory) as exc:
        resolve_category("dentst", cats)
    assert "dentist" in exc.value.suggestions
