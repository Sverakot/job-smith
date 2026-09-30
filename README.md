# job-smith

Local, LLM-assisted job search:

```
CV → profile agent → profile.json ──┐
companies.yaml → ATS workers → SQLite (dedup) → rule filters → LLM matcher → Markdown report
```

Workers discover, the database remembers, and the LLM evaluates. Everything runs on your machine with a
local model through [Ollama](https://ollama.com).

## Setup

```bash
# 1. Python env (https://docs.astral.sh/uv/)
uv sync

# 2. Local model
ollama pull qwen2.5:7b          # or qwen2.5:14b with ~16 GB VRAM; set ollama_model in config/settings.yaml

# 3. Database
uv run job-smith init
```

## Usage

```bash
# Build your profile (PDF/TXT/MD). Then OPEN data/profile.json AND EDIT IT - it drives everything.
uv run job-smith profile cv/my_cv.pdf --prefs "Tel Aviv or remote, hybrid ok, no sales/frontend"

# Put your target companies in config/companies.yaml, then:
uv run job-smith discover       # fetch jobs -> data/jobs.db, raw JSON -> raw/
uv run job-smith match --limit 20   # try a small batch first and read the scores
uv run job-smith report         # -> reports/jobs_report_YYYY-MM-DD.md
uv run job-smith status         # recent runs and failures

uv run job-smith run            # all three steps, for nightly use
```

### Tuning `profile.json`
- `title_keywords`: fragments a relevant title must contain (matched at word start, so `ml` doesn't match `HTML`).
  This is the main filter controlling how many jobs reach the LLM.
- `locations`: substring match on the job's location text. List cities **and** the country
  (`"Tel Aviv"`, `"Herzliya"`, `"Israel"`), because many postings give only the city.
- `avoid_keywords`: titles containing these are rejected.
- Editing the profile automatically marks all jobs for re-evaluation on the next `match`.
- `match --rescore` forces re-evaluation after you change the model or prompt.

### Finding company slugs
Open a company's careers page and check where the job links point:
`boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`, or `jobs.ashbyhq.com/<slug>`.

## Nightly run

Linux/macOS cron (runs at 22:00):
```
0 22 * * * cd /path/to/job-smith && /path/to/uv run job-smith run >> data/nightly.log 2>&1
```
On Windows, use Task Scheduler with the same command.

## Querying the data

```sql
sqlite3 data/jobs.db
SELECT j.title, j.company, m.score FROM jobs j JOIN matches m ON m.job_id = j.id
WHERE m.score >= 75 ORDER BY m.score DESC;

UPDATE jobs SET status = 'applied' WHERE id = 42;   -- hides it from future reports
```

## Checking match quality
Hand-label about 30 jobs as good or bad fits, then compare them with the scores. Re-check after
every prompt or model change. The scoring prompt is in `job_smith/agents/matcher.py`.

## Tests
```bash
uv run pytest
```

## Roadmap

Where this is going: an orchestrator with a persisted task queue, many discovery sources focused on
jobs in Israel, and a separate evaluation stage. Still local, still one SQLite file as the only state.

```
CV → profile agent → profile.json (incl. search_queries)
                          │
companies table ──► planner (code) ──► tasks table ──► orchestrator
                                                          │
             ┌──────────────┬──────────────┬──────────────┤
         fetch_ats    scout_company  extract_listing  fetch_detail
        (parsers)     (detect ATS)   (LLM extractor)  (LLM extractor)
             └──────────────┴──────┬───────┴──────────────┘
                          shared fetch layer (robots.txt, throttle)
                                   ▼
        SQLite (dedup) → rule filters → [triage] → LLM matcher → report
```

Steps are done in order, one at a time. Each one leaves the pipeline working and `uv run pytest` green.

- [ ] **1. Validate V1.** Run the current pipeline on a real CV and 10–20 Israeli companies. Add a
  `labels` table, `job-smith label <job_id> good|bad` and `job-smith eval` (scores vs. labels for the
  current model). *Done when:* ~30 jobs are labelled, `eval` prints the comparison, and the problems
  found (location filter, Hebrew postings, description truncation, model quality) are fixed or listed here.
- [ ] **2. Migrations + `companies` table.** Numbered migrations tracked with `PRAGMA user_version`.
  Companies move into the DB; YAML and CSV become import formats (`job-smith companies import <file>`).
  *Done when:* an existing `jobs.db` upgrades in place without losing data, and `discover` reads companies from the DB.
- [ ] **3. LLM provider interface.** Backends behind `structured()`: Ollama (native) and
  OpenAI-compatible (LM Studio, llama.cpp, vLLM, hosted APIs). Model selectable per role
  (profile / extractor / matcher) in `settings.yaml`. Hosted use is opt-in; API keys come from
  environment variables. *Done when:* switching backend is a config change and both are tested with mocked HTTP.
- [ ] **4. Shared fetch layer.** One module every worker fetches through: `robots.txt` check,
  per-host throttle, identifying User-Agent. *Done when:* no worker creates its own HTTP client.
- [ ] **5. Task queue + orchestrator.** `tasks` table (`kind`, `payload`, `status`, `attempt`,
  `heartbeat`, `error`). `run` plans tasks, then works through them; a `running` task with a stale
  heartbeat is reclaimed on the next start; after N failed attempts a task is marked `failed` and
  the run continues. Per-task timeout, per-source page cap, `run --time-budget`. Existing ATS
  discovery becomes `fetch_ats` tasks; `tasks` replaces `runs`. Jobs not seen for N days are marked
  closed. *Done when:* killing `run` midway and starting it again finishes only the remaining work.
- [ ] **6. More ATS APIs.** Comeet first (common among Israeli startups), then other public ATS
  job-board APIs. *Done when:* each has a fixture-tested parser and runs as a `fetch_ats` task.
- [ ] **7. Bulk seeding, then source scout.** Import a list of Israeli tech companies; a
  `scout_company` task fetches each careers page and detects the ATS and slug (URL patterns first).
  *Done when:* a company given only as a name + careers URL ends up with a working source or a recorded reason why not.
- [ ] **8. LLM extractor.** For careers pages with no known ATS: `extract_listing` (page → title +
  URL pairs) and `fetch_detail` (job URL → description). Every extracted URL must appear among the
  page's links and every title in its text; anything else is discarded. Pages with no usable static
  HTML are flagged `needs_browser`. Includes `job-smith add <url>` for jobs you found yourself.
  *Done when:* a non-ATS careers page yields jobs in the DB and the guard is covered by tests.
- [ ] **9. Search queries + keyword-search sources.** The profile agent writes a hand-editable
  `search_queries` list (including Hebrew variants) into `profile.json`; the planner turns it into
  tasks for sources that support keyword search. Which boards and aggregator APIs cover Israel and
  pass the scraping rule is researched in this step. *Done when:* at least one keyword-search source runs from `search_queries`.
- [ ] **10. Report stats.** Found / unique / count per decision at the top of the report.
- [ ] **11. Triage stage (optional).** A small encoder decision model (e.g.
  [Laya](https://huggingface.co/blog/sora-2/laya-ai-model-how-it-works-run-it-locally-and-eval))
  between the rule filters and the LLM matcher, to cut LLM calls. It answers typed questions and
  writes no text, so the matcher still produces the explanations. *Done when:* `eval` shows whether
  it agrees with the labels; it is kept only if it does.
- [ ] **12. Semantic dedup.** Multilingual embeddings through the provider interface, compared only
  within the same company, merged above a threshold, with merges logged so they can be undone.

### Later, unordered
Parallel fetch pool (LLM calls stay serialized), Playwright for `needs_browser` companies,
notifications, a small UI (Datasette or Streamlit).

### Source policy
Public pages only, no login, `robots.txt` honored, requests rate-limited per host and identified by
User-Agent, anti-bot measures never circumvented. A site that blocks the worker is dropped as a source.
LinkedIn is excluded for this reason; use `job-smith add <url>` (step 8) for jobs you find there by hand.

Postings are stored in their original language (Hebrew included); the matcher answers in English.
