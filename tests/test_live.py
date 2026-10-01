"""Opt-in smoke test against real OpenStreetMap services: `uv run pytest -m live`.

Needs a real contact in LH_USER_AGENT (.env). Keeps usage light: one small query, no enrichment.
"""

from __future__ import annotations

import pytest

from leadharvest.categories import load_categories
from leadharvest.config import load_settings
from leadharvest.exporters.csv_export import CsvExporter
from leadharvest.pipeline import Pipeline
from leadharvest.storage.db import connect
from leadharvest.storage.repository import Repository


@pytest.mark.live
async def test_live_search_and_clean_makati(tmp_path) -> None:
    settings = load_settings(
        db_path=tmp_path / "leads.db", export_dir=tmp_path / "exports", log_dir=tmp_path / "logs"
    )
    settings.require_network_identity()
    repo = Repository(connect(settings.db_path))
    pipeline = Pipeline(settings, repo, exporter_factory=lambda n: CsvExporter(settings.export_dir))
    cat = load_categories()["dentist"]
    run = pipeline.create_run(cat, "Makati, Philippines", limit=10, targets=["csv"])
    result = await pipeline.execute(run.id, cat, stop_after="clean")
    assert result.area_kind == "area"
    assert result.stats["clean"]["leads"] > 0
