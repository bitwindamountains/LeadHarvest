# LeadHarvest — Production Plan

2026-10-01 · Spec: `01_LeadHarvest_Blueprint.md` v1.1 (copied to `leadharvest/docs/BLUEPRINT.md`, which is canonical from now on)

"Production" for this product means: an operator (you or a trained VA) can run paid client jobs on Windows/macOS/Linux, the output is correct and compliant, failures are recoverable, and the repo is safe to make public. There is no server to deploy in the MVP.

---

## 1. Scope of this build

| In this build | Owner after this build |
|---|---|
| Blueprint Phases 0–6 (the MVP) | — |
| CI (GitHub Actions: ruff + pytest on Windows and Ubuntu) | You: push the repo to GitHub |
| README, operator runbook, `.env.example`, sample fixtures | You: record the demo (Phase 7.2) |
| Release hygiene: version, CHANGELOG, secret-free repo | You: first live run with your real contact email in `LH_USER_AGENT` |
| | You: decisions D1 (Places terms) and D2 (ODbL) before selling |

**Status (2026-10-01):** MVP committed as 0.1.0. V1 (Playwright `--js`, scoring + flags, MX check, directory adapters, HubSpot, Streamlit UI) has been built as 0.2.0 at the owner's request, ahead of the live Definition-of-Done run. Google Places stays on hold (D1). V2 (tech signals, batch, weekly monitor + encrypted-DB GitHub Actions workflow) has been built as 0.3.0, also at the owner's request. The whole roadmap is now built except Places; what remains is the owner's live verification and Phase 7 (demo, public repo).

## 2. Repository

- Location: `C:\Users\pc\Desktop\app ideas\LeadHarvest\leadharvest\`, its own git repo (branch `main`).
- Layout: as in blueprint section 8.
- Tooling: uv (installed via `python -m pip install --user uv`; on this machine call it as `python -m uv` until its script folder is on PATH), Python 3.12, ruff, pytest.

## 3. Build order and gates

| Step | Content | Gate |
|---|---|---|
| 1 | Phase 0: scaffold, config, logging, `http.py` | `pytest` + `ruff` green |
| 2 | Phase 1: models, schema, db, repository | Repository tests green |
| 3 | Phase 3.1 + 4.3: normalize + extractors (pure) | Blueprint section 14 cases green |
| 4 | Phase 2: categories, Nominatim, Overpass | Fixture tests green |
| 5 | Phase 3.2–3.3: dedupe + clean step | Dedupe gate cases green |
| 6 | Phase 4: netguard, robots, fetcher, discovery, enricher | respx gate cases green |
| 7 | Phase 5: CSV, XLSX, Sheets | Fake-worksheet gate cases green |
| 8 | Phase 6: pipeline, CLI, resume, forget/purge, integration test | Offline Definition of Done items green |
| 9 | Production hardening (section 4) | CI config valid; secret scan clean |

## 4. Production hardening (beyond the blueprint MVP list)

**Reliability**
- Every step is idempotent and resumable; `KeyboardInterrupt` → `partial` (Windows-safe).
- Overpass fallback URLs + tenacity retries; per-host circuit breaker.
- SQLite in WAL mode; `leadharvest runs` shows state; the DB file is the only state.

**Security and compliance**
- SSRF guard on every hop; robots.txt per origin; UA placeholder guard.
- Secrets only in `.env` / `secrets/` (gitignored); log redaction filter; errors stored without secrets.
- Sheets RAW writes; CSV formula escaping.
- `forget` + suppression list; `purge` retention; ODbL attribution in every export.

**Operations (runbook in the README)**
- Backups: copy `data/leads.db` (WAL checkpointed) before upgrades; `leadharvest` never deletes it.
- Upgrades: `uv lock --upgrade` monthly, then the full test suite.
- Logs: `data/logs/run-<id>.jsonl` per run; attach it when debugging a client job.
- Client job checklist: confirm source coverage for the area, run, review `possible_duplicates`, export, spot-check 10 leads, deliver with the ODbL note.

**Quality**
- CI on `windows-latest` and `ubuntu-latest`; tests never touch the network (`-m live` excluded).
- Coverage target ≥ 80% on `clean/` and `enrich/extractors.py`.

## 5. Verification before calling it done

1. `uv run pytest` green with the network unplugged (offline by design: respx blocks unmocked calls).
2. `uv run ruff check .` and `uv run ruff format --check .` clean.
3. CLI smoke: `leadharvest --help`, `categories`, a fixture-driven `run` in the integration test.
4. Manual (you): one live `run --limit 20` with your real UA contact, then a Sheets export to a test sheet.

## 6. Known limitations at release

- Coverage outside Metro Manila depends on OSM; set expectations in proposals.
- Chain branches sharing one website in one city merge (blueprint 10.4).
- Live behavior against real Overpass/Nominatim/Sheets is untested until your first live run (step 5.4); the fixtures mirror documented response formats.
