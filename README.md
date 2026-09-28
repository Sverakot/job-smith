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

## Roadmap (V2)
- `tasks` table with heartbeats/retries → a real orchestrator that can resume after a restart
- More workers: Comeet (widely used by Israeli startups), company career sites via Playwright
- Semantic deduplication with embeddings
- Detect closed jobs (not seen for N days)
- Notifications, and a small UI (Datasette or Streamlit)

LinkedIn is intentionally not included: its terms prohibit automated scraping.
