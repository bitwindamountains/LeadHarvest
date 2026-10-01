"""Step orchestration and resume (blueprint sections 5 and 7).

Each step reads from and writes to SQLite and is idempotent, so `resume` restarts at
`current_step` and a crash loses at most the in-flight item.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

import httpx

from leadharvest.categories import Category
from leadharvest.clean.dedupe import post_enrich_duplicates
from leadharvest.clean.step import run_clean_step
from leadharvest.config import Settings
from leadharvest.enrich.enricher import Enricher
from leadharvest.enrich.fetcher import PoliteFetcher
from leadharvest.enrich.mx import MxChecker, MxLookup, dns_mx_lookup
from leadharvest.enrich.netguard import Resolver, system_resolver
from leadharvest.enrich.render import PlaywrightRenderer, Renderer, RenderUnavailable
from leadharvest.exporters.base import Exporter, ExportError
from leadharvest.geo.nominatim import GeoError, LocationNotFound, NominatimClient
from leadharvest.http import Clock, Sleep, make_client
from leadharvest.logging_setup import get_logger
from leadharvest.models import STEPS, ExportResult, Run, SearchQuery, Step, new_run_id, utcnow_iso
from leadharvest.scoring import run_score_step
from leadharvest.sources.base import Source, SourceError
from leadharvest.sources.directory import (
    DirectoryConfigError,
    DirectorySource,
    load_directory_config,
)
from leadharvest.sources.osm_overpass import OsmOverpassSource, OverpassClient
from leadharvest.storage.repository import Repository

log = get_logger("pipeline")


class Reporter(Protocol):
    def step_started(self, step: str, total: int | None = None) -> None: ...
    def step_progress(self, step: str, done: int, total: int) -> None: ...
    def step_finished(self, step: str) -> None: ...


class NullReporter:
    def step_started(self, step: str, total: int | None = None) -> None:
        pass

    def step_progress(self, step: str, done: int, total: int) -> None:
        pass

    def step_finished(self, step: str) -> None:
        pass


SourcesFactory = Callable[[httpx.AsyncClient, Run, PoliteFetcher], list[Source]]
ExporterFactory = Callable[[str], Exporter]
RendererFactory = Callable[[PoliteFetcher], AbstractAsyncContextManager[Renderer]]

# Errors that pause the run (status `partial`, resumable) rather than fail it.
PAUSING_ERRORS = (SourceError, GeoError, ExportError, RenderUnavailable, DirectoryConfigError)


def default_sources(settings: Settings, sleep: Sleep = asyncio.sleep) -> SourcesFactory:
    """Build the run's sources: "osm" and/or "directory:<name>"."""

    def build(client: httpx.AsyncClient, run: Run, fetcher: PoliteFetcher) -> list[Source]:
        sources: list[Source] = []
        for name in run.sources:
            if name == "osm":
                sources.append(OsmOverpassSource(OverpassClient(settings, client, sleep=sleep)))
            elif name.startswith("directory:"):
                config = load_directory_config(name.split(":", 1)[1])
                sources.append(DirectorySource(config, fetcher))
            else:
                raise SourceError(f"Unknown source '{name}'. Use osm or directory:<name>.")
        return sources

    return build


def default_renderer(settings: Settings) -> RendererFactory:
    def build(fetcher: PoliteFetcher) -> AbstractAsyncContextManager[Renderer]:
        return PlaywrightRenderer(settings, fetcher)

    return build


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        *,
        exporter_factory: ExporterFactory,
        sources_factory: SourcesFactory | None = None,
        renderer_factory: RendererFactory | None = None,
        mx_lookup: MxLookup = dns_mx_lookup,
        resolver: Resolver = system_resolver,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        reporter: Reporter | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.exporter_factory = exporter_factory
        self.sources_factory = sources_factory or default_sources(settings, sleep)
        self.renderer_factory = renderer_factory or default_renderer(settings)
        self.mx_lookup = mx_lookup
        self.resolver = resolver
        self.clock = clock
        self.sleep = sleep
        self.reporter = reporter or NullReporter()
        self.client_factory = client_factory or (lambda: make_client(settings))

    # ---- run lifecycle ----------------------------------------------------------------------

    def create_run(
        self,
        category: Category,
        location: str,
        *,
        limit: int,
        targets: list[str],
        sources: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> Run:
        run = Run(
            id=new_run_id(),
            category=category.key,
            location=location,
            sources=sources or ["osm"],
            limit_n=limit,
            export_targets=targets,
            options=options or {},
            created_at=utcnow_iso(),
        )
        self.repo.create_run(run)
        return run

    def _reload(self, run_id: str) -> Run:
        run = self.repo.get_run(run_id)
        if run is None:
            raise KeyError(f"run not found: {run_id}")
        return run

    def make_fetcher(self, client: httpx.AsyncClient) -> PoliteFetcher:
        return PoliteFetcher(
            self.settings, client, repo=self.repo, resolver=self.resolver,
            clock=self.clock, sleep=self.sleep,
        )  # fmt: skip

    async def execute(
        self,
        run_id: str,
        category: Category,
        *,
        stop_after: Step | None = None,
        any_country: bool = False,
    ) -> Run:
        """Run from the run's current_step to the end (or through `stop_after`)."""
        self.repo.update_run(run_id, status="running", error=None, finished_at=None)
        try:
            async with self.client_factory() as client:
                # One fetcher per execution: per-host delays and the circuit breaker are
                # shared by directory scraping and website enrichment.
                fetcher = self.make_fetcher(client)
                while True:
                    run = self._reload(run_id)
                    step = run.current_step
                    if step == "done":
                        break
                    await self._run_step(step, run, category, client, fetcher, any_country)
                    self.repo.update_run_step(run_id, STEPS[STEPS.index(step) + 1])
                    if stop_after == step:
                        break
            final = self._reload(run_id)
            if final.current_step == "done":
                self.repo.update_run(run_id, status="completed", finished_at=utcnow_iso())
            else:
                self.repo.update_run(run_id, status="partial")
        except LocationNotFound as exc:
            self.repo.update_run(run_id, status="failed", error=str(exc), finished_at=utcnow_iso())
            raise
        except PAUSING_ERRORS as exc:
            log.error("Run %s stopped: %s", run_id, exc)
            self.repo.update_run(run_id, status="partial", error=str(exc)[:500])
        except (asyncio.CancelledError, KeyboardInterrupt):
            self.repo.update_run(run_id, status="partial", error="interrupted")
            raise
        except Exception as exc:
            log.exception("Run %s failed", run_id)
            self.repo.update_run(
                run_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500],
                finished_at=utcnow_iso(),
            )  # fmt: skip
            raise
        return self._reload(run_id)

    async def _run_step(
        self,
        step: Step,
        run: Run,
        category: Category,
        client: httpx.AsyncClient,
        fetcher: PoliteFetcher,
        any_country: bool,
    ) -> None:
        self.reporter.step_started(step)
        log.info("step start", extra={"data": {"run_id": run.id, "step": step}})
        started = time.monotonic()
        if step == "search":
            stats = await self.search(run, category, client, fetcher, any_country=any_country)
        elif step == "clean":
            stats = run_clean_step(self.repo, run, self.settings)
        elif step == "enrich":
            stats = await self.enrich(run, fetcher)
        elif step == "score":
            stats = await self.score(run)
        elif step == "export":
            stats = {"results": [r.model_dump() for r in self.export(run, run.export_targets)]}
        else:  # pragma: no cover
            raise ValueError(step)
        stats["seconds"] = round(time.monotonic() - started, 1)
        self.repo.merge_run_stats(run.id, {step: stats})
        log.info("step end", extra={"data": {"run_id": run.id, "step": step, "stats": stats}})
        self.reporter.step_finished(step)

    # ---- steps ------------------------------------------------------------------------------

    async def search(
        self,
        run: Run,
        category: Category,
        client: httpx.AsyncClient,
        fetcher: PoliteFetcher,
        *,
        any_country: bool = False,
    ) -> dict[str, Any]:
        area = run.resolved_area()
        alternatives: list[str] = []
        if area is None:
            geo = NominatimClient(self.settings, client, self.repo)
            area, alternatives = await geo.resolve(run.location, any_country=any_country)
            self.repo.update_run(
                run.id, area_id=area.area_id, area_kind=area.kind,
                bbox=list(area.bbox) if area.bbox else None, area_name=area.name,
            )  # fmt: skip
        query = SearchQuery(
            category=category.key, osm_tags=category.osm_tags, location=run.location,
            area=area, limit=run.limit_n,
        )  # fmt: skip
        stats: dict[str, Any] = {
            "area": area.display_name or area.name,
            "area_kind": area.kind,
            "other_matches": alternatives,
        }
        for source in self.sources_factory(client, run, fetcher):
            records = await source.search(query)
            saved = sum(self.repo.save_raw(run.id, r) for r in records)
            stats[f"{source.name}_records"] = len(records)
            stats[f"{source.name}_saved"] = saved
            total = getattr(source, "last_total", None)
            if total is not None:
                stats[f"{source.name}_total_available"] = total
        return stats

    @contextlib.asynccontextmanager
    async def _renderer(self, run: Run, fetcher: PoliteFetcher) -> AsyncIterator[Renderer | None]:
        if not run.options.get("js"):
            yield None
            return
        async with self.renderer_factory(fetcher) as renderer:
            yield renderer

    async def enrich(
        self,
        run: Run,
        fetcher: PoliteFetcher,
        *,
        retry_failed: bool = False,
        refresh_days: int | None = None,
    ) -> dict[str, Any]:
        async with self._renderer(run, fetcher) as renderer:
            enricher = Enricher(self.settings, self.repo, fetcher, renderer=renderer)
            stats = await enricher.enrich_run(
                run.id,
                retry_failed=retry_failed,
                refresh_days=refresh_days,
                on_progress=lambda done, total: self.reporter.step_progress("enrich", done, total),
            )
        stats["possible_duplicates"] = post_enrich_duplicates(
            self.repo, run.id, radius_m=self.settings.phone_match_radius_m
        )
        return stats

    async def enrich_only(
        self, run_id: str, *, retry_failed: bool = False, refresh_days: int | None = None
    ) -> dict[str, Any]:
        run = self._reload(run_id)
        async with self.client_factory() as client:
            self.reporter.step_started("enrich")
            stats = await self.enrich(
                run, self.make_fetcher(client), retry_failed=retry_failed,
                refresh_days=refresh_days,
            )  # fmt: skip
            self.reporter.step_finished("enrich")
        self.repo.merge_run_stats(run_id, {"enrich": stats})
        if run.current_step not in ("search", "clean", "enrich"):
            # Leads changed after scoring: re-score so the export reflects them.
            self.repo.merge_run_stats(run_id, {"score": await self.score(run)})
        return stats

    async def score(self, run: Run) -> dict[str, Any]:
        use_mx = run.options.get("mx", self.settings.mx_check)
        mx = MxChecker(self.repo, self.mx_lookup) if use_mx else None
        return await run_score_step(self.repo, run, mx)

    def new_since_previous(self, run: Run) -> tuple[list, Run | None]:
        """Monitoring: leads in this run that the previous completed run of the same
        category and area did not include. With no previous run, every lead is new."""
        previous = self.repo.previous_run(run)
        if previous is None:
            return self.repo.leads_for_run(run.id), None
        return self.repo.leads_not_in_run(run.id, previous.id), previous

    def export(self, run: Run, targets: list[str]) -> list[ExportResult]:
        leads = self.repo.leads_for_run(run.id)
        monitor = bool(run.options.get("monitor"))
        new_leads, previous = self.new_since_previous(run) if monitor else ([], None)
        results: list[ExportResult] = []
        failures: list[str] = []
        for target in targets:
            try:
                exporter = self.exporter_factory(target)
                results.append(exporter.export(leads, run))
                export_new = getattr(exporter, "export_new", None)
                if monitor and export_new is not None:
                    results.append(export_new(new_leads, run))
            except Exception as exc:  # keep files already written; report the rest
                log.error("Export to %s failed: %s", target, exc)
                failures.append(f"{target}: {exc}")
        stats: dict[str, Any] = {"export_results": [r.model_dump() for r in results]}
        if monitor:
            stats["monitor"] = {
                "new_since_last_run": len(new_leads),
                "previous_run": previous.id if previous else None,
            }
        self.repo.merge_run_stats(run.id, stats)
        if failures:
            raise ExportError("; ".join(failures))
        return results
