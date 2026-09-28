import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .config import Settings

TEMPLATES = Path(__file__).parent / "templates"


def build_report(settings: Settings, conn) -> Path:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    s = {
        "total": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        "new_24h": conn.execute("SELECT COUNT(*) FROM jobs WHERE first_seen >= ?", (since,)).fetchone()[0],
        "filtered": conn.execute("SELECT COUNT(*) FROM matches WHERE filtered = 1").fetchone()[0],
        "scored": conn.execute("SELECT COUNT(*) FROM matches WHERE filtered = 0").fetchone()[0],
    }
    for d in ("strong_match", "match", "weak_match", "reject"):
        s[d] = conn.execute("SELECT COUNT(*) FROM matches WHERE decision = ?", (d,)).fetchone()[0]

    rows = conn.execute(
        """SELECT j.id, j.title, j.company, j.location, j.first_seen, m.score, m.skills, m.experience,
                  m.location AS location_score, m.career_goal, m.decision, m.reasons, m.concerns,
                  (SELECT url FROM job_sources WHERE job_id = j.id ORDER BY first_seen LIMIT 1) AS url,
                  (SELECT group_concat(DISTINCT source) FROM job_sources WHERE job_id = j.id) AS sources
           FROM jobs j JOIN matches m ON m.job_id = j.id
           WHERE m.filtered = 0 AND m.score >= ? AND j.status NOT IN ('ignored', 'applied')
           ORDER BY m.score DESC, j.first_seen DESC LIMIT ?""",
        (settings.report_min_score, settings.report_top_n),
    ).fetchall()
    jobs = []
    for r in rows:
        j = dict(r)
        j["reasons"] = json.loads(j["reasons"] or "[]")
        j["concerns"] = json.loads(j["concerns"] or "[]")
        j["is_new"] = j["first_seen"] >= since
        jobs.append(j)

    failed = conn.execute(
        "SELECT DISTINCT target FROM runs WHERE kind = 'discover' AND status = 'failed' AND started_at >= ?",
        (since,),
    ).fetchall()

    env = Environment(loader=FileSystemLoader(TEMPLATES), keep_trailing_newline=True)
    text = env.get_template("report.md.j2").render(
        date=date.today().isoformat(), s=s, jobs=jobs, failed_runs=failed, min_score=settings.report_min_score)

    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    out = settings.reports_dir / f"jobs_report_{date.today().isoformat()}.md"
    out.write_text(text, encoding="utf-8")
    return out
