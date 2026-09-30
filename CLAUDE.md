# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Uses [uv](https://docs.astral.sh/uv/) (Python >= 3.11). The LLM is a local Ollama model (`ollama pull qwen2.5:7b`).

```bash
uv sync                                   # install deps (incl. dev group: pytest)
uv run pytest                             # all tests (no network, no Ollama needed)
uv run pytest tests/test_filters.py::test_name   # single test
uv run job-smith -v <cmd>                 # CLI; cmds: init | profile <cv> [--prefs] [--force] | discover | match [--limit N] [--rescore] | report | run | status
```

No linter/formatter is configured.

## Architecture

Pipeline: `CV → profile agent → data/profile.json` and `config/companies.yaml → ATS workers → SQLite (dedup) → rule filters → LLM matcher → Markdown report`.

Design principle: **the SQLite DB is the only state; workers and agents are stateless.** Workers only capture data (never judge fit); the matcher only evaluates.

- `config.py` — `Settings` (pydantic) loaded from `config/settings.yaml`. Relative paths are resolved against the **repo root** (`ROOT`), not the CWD. Runtime outputs go to `data/` (DB, profile), `raw/` (raw API JSON per ATS/slug/date), `reports/`.
- `llm.py` — `structured(settings, system, user, ModelCls)`: calls Ollama `/api/chat` with the Pydantic JSON schema as `format`, validates, and on validation failure feeds the error back and retries. Schema keywords like `minimum`/`maximum` are stripped for the grammar engine but still enforced by Pydantic. Raises `LLMError`; the matcher aborts the whole run on "request failed" (Ollama down) but skips a job on validation failure.
- `models.py` — shared schemas: `Profile` (LLM-generated, then hand-edited by the user), `JobPosting` (one job at one source), `MatchResult` (LLM score output). Field `description`s double as LLM instructions.
- `db.py` — schema + dedup. Canonical `jobs` ← many `job_sources`. Dedup levels: (1) same URL, (2) same `(source, source_job_id)`, (3) same normalized `company|title|location` `dedup_key` (with synonym expansion like `sr→senior`, `ml→machine learning`). `runs` table logs every discover/match run (shown by `status`).
- `workers/ats_boards.py` — Greenhouse/Lever/Ashby public JSON APIs. Parsers are pure functions (`parse_<ats>`, registered in `PARSERS`, URL in `ENDPOINTS`) tested against fixtures in `tests/test_parsers.py`; network code is separate. A failing company is logged as a failed run and doesn't stop others. To add an ATS: add endpoint, parser, `PARSERS` entry, and extend the `Company.ats` Literal.
- `filters.py` — cheap pre-LLM `hard_filter` (avoid/title keywords matched at word start so `ml` ≠ `HTML`, seniority, location). Unknown location passes through to the LLM.
- `agents/matcher.py` — re-evaluation is driven by `profile_hash` (sha of profile JSON): jobs whose `matches.profile_hash` differs are re-scored, so editing `profile.json` automatically triggers re-matching; `--rescore` sets all hashes to `'stale'`. The scoring prompt (`SYSTEM`) lives here.
- `agents/profile.py` — CV (PDF/TXT/MD) → `profile.json` + `profile.md`; refuses to overwrite without `--force` because users hand-edit the JSON.
- `report.py` + `templates/report.md.j2` — top matches above `report_min_score`, excluding jobs with `status` `applied`/`ignored`.
- `cli.py` — argparse entry point; imports agents/workers lazily. Expected user-facing errors (`FileNotFoundError`, `FileExistsError`, `ValueError`, `LLMError`) are caught and turned into exit code 1.

## Testing conventions

`tests/conftest.py` provides `settings` (all paths under `tmp_path`, `request_delay_s=0`), `conn`, and `profile` fixtures. Tests mock the LLM by monkeypatching `matcher.structured` (see `tests/test_pipeline.py`); never require a running Ollama or network.

## Roadmap workflow

The numbered steps, their order and each step's "Done when" live in the **Roadmap section of README.md**; read it before starting any feature work. The Architecture section above describes what exists today; update it in the same change that makes a step real.

- Work the first unchecked step, on its own branch. Tick its checkbox in README.md when its "Done when" holds and `uv run pytest` is green.
- A request that belongs to a later step: say which step it is and ask whether to reorder before building it.
- Step 1 needs the user's CV, preferences, a list of Israeli companies, a running Ollama, and their hand labels; ask for these rather than inventing stand-ins.

## Invariants

These hold across every roadmap step:

- **The SQLite DB is the only state.** Workers write through `db` directly; there are no intermediate JSONL/Markdown hand-off files. `raw/` holds evidence for replay, never state.
- **Workers capture, the matcher judges.** Discovery code stores what it found; fit is decided only in the evaluation stage (rule filters, optional triage, LLM matcher).
- **One schema-validated LLM call per step**, through `llm.structured`. The LLM is an extractor, a matcher and a profile writer; control flow (planning tasks, choosing what to fetch next) is deterministic code. Sources with a JSON API get a pure parser, not the LLM.
- **Extracted data must be grounded**: a URL or title the extractor returns is kept only if it appears literally in the fetched page.
- **Tasks are idempotent** (upserts), so the orchestrator may retry or re-run any of them. Matching is a DB-driven loop keyed on `profile_hash`, not one task per job.
- **All HTTP goes through the shared fetch layer** once it exists (step 4), which enforces the source policy: public pages, no login, `robots.txt` honored, per-host throttle, identifying User-Agent, anti-bot measures left alone. LinkedIn is excluded under this policy.
- **Local by default.** Hosted LLM backends are opt-in through config, with keys read from environment variables.
- **Postings keep their original language** (Hebrew is expected); normalization, filters and prompts must handle non-ASCII text.
- **Schema changes are numbered migrations** (`PRAGMA user_version`, from step 2); the DB holds labels and application statuses that cannot be regenerated.
