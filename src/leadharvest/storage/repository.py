"""All SQL lives here (blueprint section 7)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from leadharvest.models import Lead, RawBusiness, Run, Step, utcnow_iso

LEAD_COLUMNS: tuple[str, ...] = (
    "lead_id", "business_name", "name_key", "categories", "address", "city", "city_key",
    "city_source", "province", "street_key", "country", "lat", "lon", "phone", "phones_extra",
    "email", "emails_extra", "website", "final_url", "https_ok", "domain", "facebook",
    "instagram", "linkedin", "tiktok", "opening_hours", "sources", "enrich_status",
    "enriched_at", "enrich_error", "score", "flags", "first_seen_run_id", "first_seen_at",
    "last_seen_at", "updated_at", "tech", "mobile_viewport",
)  # fmt: skip
_LEAD_JSON = {"categories", "phones_extra", "emails_extra", "sources", "flags", "tech"}
_LEAD_BOOL = {"https_ok", "mobile_viewport"}

_RUN_UPDATABLE = {
    "area_id", "area_kind", "bbox", "area_name", "export_targets", "status", "current_step",
    "error", "finished_at", "limit_n", "options",
}  # fmt: skip
_RUN_JSON = {"sources", "export_targets", "stats", "bbox", "options"}


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ---- runs -------------------------------------------------------------------------------

    def create_run(self, run: Run) -> None:
        data = run.model_dump()
        cols = [
            "id", "category", "location", "area_id", "area_kind", "bbox", "area_name", "sources",
            "limit_n", "export_targets", "options", "status", "current_step", "stats", "error",
            "created_at", "finished_at",
        ]  # fmt: skip
        values = [
            json.dumps(data[c]) if c in _RUN_JSON and data[c] is not None else data[c] for c in cols
        ]
        self.conn.execute(
            f"INSERT INTO runs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", values
        )

    def get_run(self, run_id: str) -> Run | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def resolve_run_id(self, ref: str) -> str | None:
        """'latest', a full id, or a unique id prefix → run id."""
        if ref == "latest":
            row = self.conn.execute(
                "SELECT id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            return row["id"] if row else None
        rows = self.conn.execute(
            "SELECT id FROM runs WHERE id LIKE ? LIMIT 2", (ref.replace("%", "") + "%",)
        ).fetchall()
        return rows[0]["id"] if len(rows) == 1 else None

    def find_batch_run(self, batch: str, row: int) -> Run | None:
        """Latest run created for this batch row (see batch.py)."""
        found = self.conn.execute(
            "SELECT * FROM runs WHERE json_extract(options, '$.batch') = ? "
            "AND json_extract(options, '$.row') = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (batch, row),
        ).fetchone()
        return _row_to_run(found) if found else None

    def previous_run(self, run: Run) -> Run | None:
        """The latest earlier completed run of the same category over the same area.

        For a monitor run, only earlier runs of the same monitor count, so a one-off `run` or
        another client's monitor over the same area never becomes "last run"."""
        area_clause, params = "lower(location) = lower(?)", [run.location]
        if run.area_kind == "area" and run.area_id is not None:
            area_clause, params = "area_id = ?", [run.area_id]
        batch = run.options.get("batch")
        if run.options.get("monitor") and isinstance(batch, str) and "@" in batch:
            # Monitor batches are named "<base>@YYYY-Www" (cli.monitor_batch_name): 9-char suffix.
            area_clause += (
                " AND json_extract(options, '$.monitor') = 1 AND "
                "substr(json_extract(options, '$.batch'), 1, "
                "length(json_extract(options, '$.batch')) - 9) = ?"
            )
            params.append(batch.rsplit("@", 1)[0])
        found = self.conn.execute(
            f"SELECT * FROM runs WHERE category = ? AND {area_clause} AND id != ? "
            "AND status = 'completed' AND created_at <= ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            [run.category, *params, run.id, run.created_at],
        ).fetchone()
        return _row_to_run(found) if found else None

    def leads_not_in_run(self, run_id: str, other_run_id: str) -> list[Lead]:
        """Leads of `run_id` that `other_run_id` did not include, in run order."""
        rows = self.conn.execute(
            "SELECT l.* FROM leads l JOIN run_leads r ON r.lead_id = l.lead_id "
            "WHERE r.run_id = ? AND l.lead_id NOT IN "
            "(SELECT lead_id FROM run_leads WHERE run_id = ?) ORDER BY r.position",
            (run_id, other_run_id),
        ).fetchall()
        return [_row_to_lead(r) for r in rows]

    def list_runs(self, limit: int = 20) -> list[Run]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_run(r) for r in rows]

    def update_run(self, run_id: str, **fields: Any) -> None:
        unknown = set(fields) - _RUN_UPDATABLE
        if unknown:
            raise ValueError(f"cannot update run fields: {sorted(unknown)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        values = [
            json.dumps(v) if k in _RUN_JSON and v is not None else v for k, v in fields.items()
        ]
        self.conn.execute(f"UPDATE runs SET {assignments} WHERE id = ?", [*values, run_id])

    def update_run_step(self, run_id: str, step: Step) -> None:
        self.update_run(run_id, current_step=step)

    def merge_run_stats(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self.transaction():
            row = self.conn.execute("SELECT stats FROM runs WHERE id = ?", (run_id,)).fetchone()
            stats = json.loads(row["stats"]) if row else {}
            stats.update(updates)
            self.conn.execute("UPDATE runs SET stats = ? WHERE id = ?", (json.dumps(stats), run_id))
        return stats

    # ---- raw records ------------------------------------------------------------------------

    def save_raw(self, run_id: str, raw: RawBusiness) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO raw_records (run_id, source, source_ref, payload, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, raw.source, raw.source_ref, raw.model_dump_json(), utcnow_iso()),
        )
        return cur.rowcount == 1

    def raw_for_run(self, run_id: str) -> list[RawBusiness]:
        rows = self.conn.execute(
            "SELECT payload FROM raw_records WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [RawBusiness.model_validate_json(r["payload"]) for r in rows]

    def count_raw(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM raw_records WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row[0])

    # ---- lead lookups (dedupe rules, blueprint 10.4) -----------------------------------------

    def get_lead(self, lead_id: str) -> Lead | None:
        row = self.conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
        return _row_to_lead(row) if row else None

    def lead_by_source_ref(self, source: str, source_ref: str) -> Lead | None:
        row = self.conn.execute(
            "SELECT l.* FROM leads l JOIN lead_sources s ON s.lead_id = l.lead_id "
            "WHERE s.source = ? AND s.source_ref = ?",
            (source, source_ref),
        ).fetchone()
        return _row_to_lead(row) if row else None

    def is_source_linked(self, lead_id: str, source: str, source_ref: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM lead_sources WHERE lead_id = ? AND source = ? AND source_ref = ?",
            (lead_id, source, source_ref),
        ).fetchone()
        return row is not None

    def count_lead_sources(self, lead_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM lead_sources WHERE lead_id = ?", (lead_id,)
        ).fetchone()
        return int(row[0])

    def leads_by_phone(self, phone: str) -> list[Lead]:
        rows = self.conn.execute(
            "SELECT * FROM leads WHERE phone = ? ORDER BY first_seen_at, lead_id", (phone,)
        ).fetchall()
        return [_row_to_lead(r) for r in rows]

    def leads_by_domain_city(self, domain: str, city_key: str) -> list[Lead]:
        rows = self.conn.execute(
            "SELECT * FROM leads WHERE domain = ? AND city_key = ? ORDER BY first_seen_at, lead_id",
            (domain, city_key),
        ).fetchall()
        return [_row_to_lead(r) for r in rows]

    def leads_by_name_street_city(
        self, name_key: str, street_key: str, city_key: str
    ) -> list[Lead]:
        rows = self.conn.execute(
            "SELECT * FROM leads WHERE name_key = ? AND street_key = ? AND city_key = ? "
            "ORDER BY first_seen_at, lead_id",
            (name_key, street_key, city_key),
        ).fetchall()
        return [_row_to_lead(r) for r in rows]

    def distinct_names_for_phone(self, phone: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT name_key) FROM leads WHERE phone = ?", (phone,)
        ).fetchone()
        return int(row[0])

    # ---- lead writes ------------------------------------------------------------------------

    def insert_lead(self, lead: Lead) -> None:
        values = _lead_to_values(lead)
        self.conn.execute(
            f"INSERT INTO leads ({', '.join(LEAD_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(LEAD_COLUMNS))})",
            values,
        )

    def update_lead(self, lead: Lead) -> None:
        values = _lead_to_values(lead)
        cols = [c for c in LEAD_COLUMNS if c != "lead_id"]
        self.conn.execute(
            f"UPDATE leads SET {', '.join(f'{c} = ?' for c in cols)} WHERE lead_id = ?",
            [*values[1:], values[0]],
        )

    def upsert_lead(self, lead: Lead) -> None:
        if lead.lead_id and self.get_lead(lead.lead_id):
            self.update_lead(lead)
        else:
            self.insert_lead(lead)

    def add_lead_source(self, source: str, source_ref: str, lead_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO lead_sources (source, source_ref, lead_id) VALUES (?, ?, ?)",
            (source, source_ref, lead_id),
        )

    def link_run_lead(self, run_id: str, lead_id: str, category: str) -> bool:
        """Link a lead to a run once; returns True if this call created the link."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO run_leads (run_id, lead_id, category, position) "
            "VALUES (?, ?, ?, (SELECT COUNT(*) FROM run_leads WHERE run_id = ?))",
            (run_id, lead_id, category, run_id),
        )
        return cur.rowcount == 1

    def is_linked(self, run_id: str, lead_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM run_leads WHERE run_id = ? AND lead_id = ?", (run_id, lead_id)
        ).fetchone()
        return row is not None

    def count_run_leads(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM run_leads WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row[0])

    def leads_for_run(self, run_id: str) -> list[Lead]:
        rows = self.conn.execute(
            "SELECT l.* FROM leads l JOIN run_leads r ON r.lead_id = l.lead_id "
            "WHERE r.run_id = ? ORDER BY r.position",
            (run_id,),
        ).fetchall()
        return [_row_to_lead(r) for r in rows]

    def count_new_leads(self, run_id: str) -> int:
        """`is_new` is derived from first_seen_run_id, so resume never changes it."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM run_leads r JOIN leads l ON l.lead_id = r.lead_id "
            "WHERE r.run_id = ? AND l.first_seen_run_id = ?",
            (run_id, run_id),
        ).fetchone()
        return int(row[0])

    def mark_no_website(self, run_id: str) -> int:
        cur = self.conn.execute(
            "UPDATE leads SET enrich_status = 'no_website', updated_at = ? "
            "WHERE enrich_status = 'pending' AND (website IS NULL OR website = '') "
            "AND lead_id IN (SELECT lead_id FROM run_leads WHERE run_id = ?)",
            (utcnow_iso(), run_id),
        )
        return cur.rowcount

    def leads_to_enrich(
        self, run_id: str, *, retry_failed: bool = False, refresh_days: int | None = None
    ) -> list[Lead]:
        statuses = ["pending"]
        if retry_failed:
            statuses += ["timeout", "http_error", "failed"]
        clauses = [f"l.enrich_status IN ({', '.join('?' * len(statuses))})"]
        params: list[Any] = [run_id, *statuses]
        if refresh_days is not None:
            cutoff = (datetime.now(UTC) - timedelta(days=refresh_days)).isoformat(
                timespec="seconds"
            )
            clauses.append("(l.enrich_status = 'ok' AND l.enriched_at < ?)")
            params.append(cutoff)
        rows = self.conn.execute(
            "SELECT l.* FROM leads l JOIN run_leads r ON r.lead_id = l.lead_id "
            "WHERE r.run_id = ? AND l.website IS NOT NULL AND l.website != '' "
            f"AND ({' OR '.join(clauses)}) ORDER BY r.position",
            params,
        ).fetchall()
        return [_row_to_lead(r) for r in rows]

    def enrich_status_counts(self, run_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT l.enrich_status, COUNT(*) AS n FROM leads l "
            "JOIN run_leads r ON r.lead_id = l.lead_id WHERE r.run_id = ? GROUP BY 1",
            (run_id,),
        ).fetchall()
        return {r["enrich_status"]: int(r["n"]) for r in rows}

    # ---- privacy ----------------------------------------------------------------------------

    def add_suppression(self, kind: str, value: str, reason: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO suppressions (kind, value, reason, created_at) "
            "VALUES (?, ?, ?, ?)",
            (kind, value, reason, utcnow_iso()),
        )

    def suppressions(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {"domain": set(), "phone": set(), "email": set()}
        for row in self.conn.execute("SELECT kind, value FROM suppressions"):
            result[row["kind"]].add(row["value"])
        return result

    def is_suppressed(self, kind: str, value: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM suppressions WHERE kind = ? AND value = ?", (kind, value)
        ).fetchone()
        return row is not None

    def find_leads_for_forget(self, kind: str, value: str) -> list[str]:
        if kind == "domain":
            sql = "SELECT lead_id FROM leads WHERE domain = ?"
            params: tuple[str, ...] = (value,)
        elif kind == "phone":
            sql = (
                "SELECT lead_id FROM leads WHERE phone = ? OR EXISTS "
                "(SELECT 1 FROM json_each(leads.phones_extra) WHERE value = ?)"
            )
            params = (value, value)
        elif kind == "email":
            sql = (
                "SELECT lead_id FROM leads WHERE email = ? OR EXISTS "
                "(SELECT 1 FROM json_each(leads.emails_extra) WHERE value = ?)"
            )
            params = (value, value)
        else:
            raise ValueError(f"unknown suppression kind: {kind}")
        return [r["lead_id"] for r in self.conn.execute(sql, params)]

    def delete_leads(self, lead_ids: list[str]) -> int:
        deleted = 0
        for lead_id in lead_ids:
            cur = self.conn.execute("DELETE FROM leads WHERE lead_id = ?", (lead_id,))
            deleted += cur.rowcount
        return deleted

    def forget(self, kind: str, value: str, reason: str | None = None) -> int:
        """Delete matching leads and suppress the value so future runs don't re-collect it."""
        with self.transaction():
            lead_ids = self.find_leads_for_forget(kind, value)
            deleted = self.delete_leads(lead_ids)
            self.add_suppression(kind, value, reason)
        return deleted

    def purge(self, not_seen_days: int) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=not_seen_days)).isoformat(timespec="seconds")
        cur = self.conn.execute("DELETE FROM leads WHERE last_seen_at < ?", (cutoff,))
        return cur.rowcount

    # ---- caches -----------------------------------------------------------------------------

    def geo_cache_get(self, query_key: str) -> Any | None:
        row = self.conn.execute(
            "SELECT result FROM geo_cache WHERE query_key = ?", (query_key,)
        ).fetchone()
        return json.loads(row["result"]) if row else None

    def geo_cache_put(self, query_key: str, result: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO geo_cache (query_key, result, cached_at) VALUES (?, ?, ?)",
            (query_key, json.dumps(result), utcnow_iso()),
        )

    def robots_cache_get(
        self, origin: str, max_age_hours: float = 24
    ) -> tuple[str | None, int] | None:
        row = self.conn.execute(
            "SELECT robots_txt, status, fetched_at FROM robots_cache WHERE origin = ?", (origin,)
        ).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if datetime.now(UTC) - fetched > timedelta(hours=max_age_hours):
            return None
        return row["robots_txt"], int(row["status"])

    def mx_cache_get(self, domain: str, max_age_days: float = 30) -> bool | None:
        row = self.conn.execute(
            "SELECT has_mail, checked_at FROM mx_cache WHERE domain = ?", (domain,)
        ).fetchone()
        if not row:
            return None
        if datetime.now(UTC) - datetime.fromisoformat(row["checked_at"]) > timedelta(
            days=max_age_days
        ):
            return None
        return bool(row["has_mail"])

    def mx_cache_put(self, domain: str, has_mail: bool) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO mx_cache (domain, has_mail, checked_at) VALUES (?, ?, ?)",
            (domain, int(has_mail), utcnow_iso()),
        )

    def robots_cache_put(self, origin: str, robots_txt: str | None, status: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO robots_cache (origin, robots_txt, status, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            (origin, robots_txt, status, utcnow_iso()),
        )


def _lead_to_values(lead: Lead) -> list[Any]:
    data = lead.model_dump()
    values: list[Any] = []
    for col in LEAD_COLUMNS:
        value = data[col]
        if col in _LEAD_JSON:
            value = json.dumps(value or [], ensure_ascii=False)
        elif col in _LEAD_BOOL and value is not None:
            value = int(value)
        values.append(value)
    return values


def _row_to_lead(row: sqlite3.Row) -> Lead:
    data = {col: row[col] for col in LEAD_COLUMNS}
    for col in _LEAD_JSON:
        data[col] = json.loads(data[col] or "[]")
    for col in _LEAD_BOOL:
        if data[col] is not None:
            data[col] = bool(data[col])
    return Lead.model_validate(data)


def _row_to_run(row: sqlite3.Row) -> Run:
    data = dict(row)
    for col in _RUN_JSON:
        if data.get(col) is not None:
            data[col] = json.loads(data[col])
    return Run.model_validate(data)
