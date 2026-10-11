"""Dedupe rules (blueprint 10.4) exercised through the clean step against a real temp DB."""

from leadharvest.clean.dedupe import (
    haversine_m,
    merge,
    merge_location_duplicates,
    names_match_closely,
    names_similar,
)
from leadharvest.clean.step import candidate_from_raw, run_clean_step
from leadharvest.models import Lead, RawBusiness, Run, utcnow_iso
from leadharvest.storage.repository import Repository

# Two points in Makati ~1.1 km apart, and one ~50 m from A.
A = (14.5547, 121.0244)
A_NEAR = (14.5551, 121.0246)
B_FAR = (14.5647, 121.0244)


def new_run(repo: Repository, run_id: str = "run-1", limit: int = 200) -> Run:
    run = Run(
        id=run_id,
        category="dentist",
        location="Makati",
        area_name="Makati",
        limit_n=limit,
        created_at=utcnow_iso(),
    )
    repo.create_run(run)
    return run


def raw(ref: str, name: str, **kw: object) -> RawBusiness:
    return RawBusiness(source="osm", source_ref=ref, name=name, **kw)


def clean(repo: Repository, run: Run, settings, records: list[RawBusiness]) -> dict:
    for r in records:
        repo.save_raw(run.id, r)
    return run_clean_step(repo, run, settings)


def test_helpers() -> None:
    assert names_similar("smile dental", "smile dental clinic")
    assert names_similar("smile dental makati", "smile dental clinic makati")
    assert not names_similar("jollibee ayala", "jollibee glorietta")
    assert not names_similar("", "x")
    assert 1000 < haversine_m(*A, *B_FAR) < 1200


def test_rule0_rerun_of_same_records_creates_no_new_leads(repo, settings) -> None:
    # Name-only records match nothing by rules 1-3: only source identity prevents duplicates.
    records = [raw("node/1", "Clinic One"), raw("node/2", "Clinic Two")]
    run1 = new_run(repo, "run-1")
    assert clean(repo, run1, settings, records)["new"] == 2
    run2 = new_run(repo, "run-2")
    stats = clean(repo, run2, settings, records)
    assert stats["new"] == 0
    assert stats["existing"] == 2


def test_rule1_same_phone_similar_name_nearby_merges(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Smile Dental", phones_raw=["0917 123 4567"], lat=A[0], lon=A[1]),
        raw("way/2", "Smile Dental Clinic", phones_raw=["+63 917 123 4567"],
            lat=A_NEAR[0], lon=A_NEAR[1], website_raw="smiledental.ph"),
    ])  # fmt: skip
    assert stats["leads"] == 1
    assert stats["duplicates_merged"] == 1
    (lead,) = repo.leads_for_run(run.id)
    assert lead.website == "https://smiledental.ph"  # empty field filled from the second record


def test_rule1_chain_hotline_far_apart_does_not_merge(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Jollibee", phones_raw=["(02) 8700-0000"], lat=A[0], lon=A[1]),
        raw("node/2", "Jollibee", phones_raw=["(02) 8700-0000"], lat=B_FAR[0], lon=B_FAR[1]),
    ])  # fmt: skip
    assert stats["leads"] == 2


def test_rule1_shared_building_line_different_names_does_not_merge(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Smile Dental", phones_raw=["(02) 8123-4567"], lat=A[0], lon=A[1]),
        raw("node/2", "Bright Eyes Optical", phones_raw=["(02) 8123-4567"],
            lat=A_NEAR[0], lon=A_NEAR[1]),
    ])  # fmt: skip
    assert stats["leads"] == 2


def test_shared_phone_never_used_for_matching(repo, settings) -> None:
    settings.shared_phone_min_names = 3
    run = new_run(repo)
    clean(repo, run, settings, [
        raw(f"node/{i}", name, phones_raw=["(02) 8123-4567"], lat=A[0], lon=A[1])
        for i, name in enumerate(["Alpha Dental", "Beta Optical", "Gamma Law"])
    ])  # fmt: skip
    stats = clean(
        repo,
        run,
        settings,
        [
            # Far away, so neither the shared phone nor rule 4 (name + location) can link it.
            raw(
                "node/9", "Alpha Dental", phones_raw=["(02) 8123-4567"], lat=B_FAR[0], lon=B_FAR[1]
            ),
        ],
    )
    assert stats["leads"] == 4  # the 4th record could only have matched via the shared phone


def test_rule2_domain_and_city(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Smile Dental", website_raw="https://www.smile.com.ph", city="Makati City"),
        raw("node/2", "Smile Dental Makati Branch", website_raw="smile.com.ph/contact",
            city="Makati"),
    ])  # fmt: skip
    assert stats["leads"] == 1


def test_rule2_shared_host_domains_never_match(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Alpha", website_raw="https://alpha.wixsite.com/site", city="Makati"),
        raw("node/2", "Beta", website_raw="https://beta.wixsite.com/site", city="Makati"),
    ])  # fmt: skip
    assert stats["leads"] == 2


def test_rule2_city_falls_back_to_run_area(repo, settings) -> None:
    run = new_run(repo)
    clean(repo, run, settings, [raw("node/1", "Smile", website_raw="smile.ph")])
    (lead,) = repo.leads_for_run(run.id)
    assert lead.city == "Makati"
    assert lead.city_source == "run_area"


def test_rule3_requires_non_empty_street(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Smile Dental"), raw("node/2", "Smile Dental"),
    ])  # fmt: skip
    assert stats["leads"] == 2


def test_rule3_name_street_city(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Smile Dental", street="Rizal St.", city="Makati"),
        raw("node/2", "Smile Dental Inc.", street="Rizal Street", city="Makati City"),
        raw("node/3", "Smile Dental", street="Rizal St.", city="Pasig"),
    ])  # fmt: skip
    assert stats["leads"] == 2  # same name+street in a different city stays separate


# Live Argao pairs (2026-10-11): one place from OSM (no phone, no street) and from Overture.
KAFE, KAFE_12M = (9.8892, 123.5983), (9.8893, 123.5983)
MAAYO, MAAYO_15M = (9.8801, 123.6085), (9.8802, 123.6086)
AIS, MAXS_60M = (9.8721, 123.5949), (9.8726, 123.5946)


def overture(ref: str, name: str, **kw: object) -> RawBusiness:
    return RawBusiness(source="overture", source_ref=ref, name=name, **kw)


def test_names_match_closely() -> None:
    assert names_match_closely("bj s seaside", "bjs seaside")  # spacing only
    assert names_match_closely("maayo stay argao", "maayo argao")  # 2 of 3 tokens
    assert not names_match_closely("ai s restaurant", "max s restaurant sm")  # 0.4
    assert not names_match_closely("carinderia", "carmen s carinderia")  # containment isn't enough
    assert not names_match_closely("", "kafe marco")


def test_rule4_same_place_from_two_sources_merges(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Kafe Marco", lat=KAFE[0], lon=KAFE[1]),
        overture("o/1", "Kafe Marco", phones_raw=["032 555 0123"],
                 lat=KAFE_12M[0], lon=KAFE_12M[1]),
        raw("node/2", "BJ's Seaside", lat=MAAYO[0] + 0.01, lon=MAAYO[1]),
        overture("o/2", "BJs Seaside", lat=MAAYO[0] + 0.0101, lon=MAAYO[1]),
        raw("node/3", "Maayo stay Argao", lat=MAAYO[0], lon=MAAYO[1]),
        overture("o/3", "Maayo Argao", lat=MAAYO_15M[0], lon=MAAYO_15M[1]),
    ])  # fmt: skip
    assert stats["leads"] == 3
    kafe = next(x for x in repo.leads_for_run(run.id) if x.name_key == "kafe marco")
    assert kafe.phone == "+63325550123"  # OSM's empty phone filled from Overture
    assert set(kafe.sources) == {"osm", "overture"}


def test_rule4_needs_close_names_and_distance(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "Ai's Restaurant", lat=AIS[0], lon=AIS[1]),
        overture("o/1", "Max's Restaurant SM", lat=MAXS_60M[0], lon=MAXS_60M[1]),  # other place
        raw("node/2", "Kafe Marco", lat=KAFE[0], lon=KAFE[1]),
        overture("o/2", "Kafe Marco", lat=KAFE[0] + 0.002, lon=KAFE[1]),  # ~220 m: a branch
        overture("o/3", "Kafe Marco"),  # no coordinates: location can't vouch for it
    ])  # fmt: skip
    assert stats["leads"] == 5


def test_stored_duplicates_merge_into_the_older_lead(repo, settings) -> None:
    # Leads stored before rule 4: insert them directly so the clean step can't merge them.
    old_run, new_run_ = new_run(repo, "run-old"), new_run(repo, "run-new")
    now = utcnow_iso()
    kafe = dict(name_key="kafe marco", first_seen_at=now, last_seen_at=now, updated_at=now)
    osm = Lead(lead_id="L-old", business_name="Kafe Marco", lat=KAFE[0], lon=KAFE[1],
               sources=["osm"], score=0, first_seen_run_id="run-old", **kafe)  # fmt: skip
    ovt = Lead(lead_id="L-new", business_name="Kafe Marco", lat=KAFE_12M[0], lon=KAFE_12M[1],
               phone="+63325550123", facebook="https://www.facebook.com/1", sources=["overture"],
               first_seen_run_id="run-new", **{**kafe, "first_seen_at": now + "Z"})  # fmt: skip
    for lead, run, ref in ((osm, old_run, ("osm", "node/1")), (ovt, new_run_, ("overture", "o/1"))):
        repo.insert_lead(lead)
        repo.add_lead_source(*ref, lead.lead_id)
        repo.link_run_lead(run.id, lead.lead_id, "restaurant")

    listed = merge_location_duplicates(repo, apply=False)
    assert [(k.lead_id, d.lead_id) for k, d in listed] == [("L-old", "L-new")]
    assert repo.get_lead("L-new") is not None  # listing changes nothing

    merge_location_duplicates(repo, apply=True)
    assert repo.get_lead("L-new") is None
    kept = repo.get_lead("L-old")
    assert kept.phone == "+63325550123" and set(kept.sources) == {"osm", "overture"}
    assert kept.score > 0  # rescored with the phone and Facebook page it gained
    assert repo.lead_by_source_ref("overture", "o/1").lead_id == "L-old"
    assert repo.is_linked("run-new", "L-old") and repo.is_linked("run-old", "L-old")
    assert merge_location_duplicates(repo, apply=False) == []


def test_conflicting_matches_are_reported(repo, settings) -> None:
    run = new_run(repo)
    clean(repo, run, settings, [
        raw("node/1", "Smile Dental", phones_raw=["0917 123 4567"], lat=A[0], lon=A[1]),
        raw("node/2", "Other Clinic", website_raw="smile.ph", city="Makati"),
    ])  # fmt: skip
    stats = clean(repo, run, settings, [
        raw("node/3", "Smile Dental", phones_raw=["0917 123 4567"], website_raw="smile.ph",
            city="Makati", lat=A[0], lon=A[1]),
    ])  # fmt: skip
    assert stats["leads"] == 2
    assert len(stats["possible_duplicates"]) == 1


def test_limit_truncates_and_rerun_is_stable(repo, settings) -> None:
    run = new_run(repo, limit=2)
    records = [raw(f"node/{i}", f"Clinic {i}") for i in range(5)]
    stats = clean(repo, run, settings, records)
    assert stats["leads"] == 2
    assert stats["truncated"] is True
    again = run_clean_step(repo, run, settings)
    assert again["leads"] == 2
    assert again["new"] == 2


def test_suppressed_records_are_dropped(repo, settings) -> None:
    repo.add_suppression("domain", "smile.ph")
    repo.add_suppression("phone", "+639171234567")
    run = new_run(repo)
    stats = clean(repo, run, settings, [
        raw("node/1", "A", website_raw="https://smile.ph"),
        raw("node/2", "B", phones_raw=["0917 123 4567"]),
        raw("node/3", "C", emails_raw=["info@smile.ph"]),
        raw("node/4", "D"),
    ])  # fmt: skip
    assert stats["suppressed"] == 3
    assert stats["leads"] == 1


def test_unnamed_records_skipped_and_no_website_marked(repo, settings) -> None:
    run = new_run(repo)
    stats = clean(repo, run, settings, [raw("node/1", "  "), raw("node/2", "Named")])
    assert stats["unnamed_skipped"] == 1
    (lead,) = repo.leads_for_run(run.id)
    assert lead.enrich_status == "no_website"


def test_merge_refresh_of_same_record_overwrites_source_fields(repo, settings) -> None:
    run = new_run(repo)
    existing = candidate_from_raw(raw("node/1", "Smile", phones_raw=["0917 123 4567"]), run)
    existing.lead_id = "L-1"
    refreshed = candidate_from_raw(raw("node/1", "Smile", phones_raw=["0918 765 4321"]), run)
    other = candidate_from_raw(raw("node/2", "Smile", phones_raw=["0918 765 4321"]), run)
    assert merge(existing, refreshed, same_source_record=True).phone == "+639187654321"
    assert merge(existing, other, same_source_record=False).phone == "+639171234567"
    assert merge(existing, other, same_source_record=False).lead_id == "L-1"


def test_merge_resets_enrichment_when_website_changes(repo, settings) -> None:
    run = new_run(repo)
    existing = candidate_from_raw(raw("node/1", "Smile", website_raw="old.ph"), run)
    existing.enrich_status = "ok"
    refreshed = candidate_from_raw(raw("node/1", "Smile", website_raw="new.ph"), run)
    assert merge(existing, refreshed, same_source_record=True).enrich_status == "pending"


def test_candidate_social_handles_and_address(repo, settings) -> None:
    run = new_run(repo)
    cand = candidate_from_raw(raw(
        "node/1", "Smile", housenumber="12", street="Rizal St", suburb="Poblacion",
        city="Makati", facebook="SmileDentalPH", instagram="@smile.ph",
        website_raw="https://facebook.com/smile",
    ), run)  # fmt: skip
    assert cand.address == "12 Rizal St, Poblacion, Makati"
    assert cand.facebook == "https://facebook.com/smile"
    assert cand.instagram == "https://www.instagram.com/smile.ph"
    assert cand.website is None
    other = candidate_from_raw(raw(
        "node/2", "B", facebook="SmileDentalPH", instagram="https://example.org/not-instagram",
    ), run)  # fmt: skip
    assert other.facebook == "https://www.facebook.com/SmileDentalPH"
    assert other.instagram is None
