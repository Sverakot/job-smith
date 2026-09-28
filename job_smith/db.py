"""SQLite storage. The database is the system's state; agents and workers are stateless.

Deduplication (canonical job <- many sources):
  Level 1: identical URL
  Level 2: identical (source, source_job_id)
  Level 3 (lite): identical normalized company + title + location
Semantic dedup (embeddings / LLM) is a V2 item.
"""
import json
import re
import sqlite3
from pathlib import Path

from .models import JobPosting, MatchResult, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,
    dedup_key   TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT,
    remote      INTEGER,
    description TEXT,
    posted_at   TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new'   -- new | seen | applied | ignored
);
CREATE TABLE IF NOT EXISTS job_sources (
    id            INTEGER PRIMARY KEY,
    job_id        INTEGER NOT NULL REFERENCES jobs(id),
    source        TEXT NOT NULL,
    source_job_id TEXT,
    url           TEXT NOT NULL UNIQUE,
    raw_path      TEXT,
    search_query  TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    UNIQUE (source, source_job_id)
);
CREATE TABLE IF NOT EXISTS matches (
    job_id        INTEGER PRIMARY KEY REFERENCES jobs(id),
    profile_hash  TEXT NOT NULL,
    filtered      INTEGER NOT NULL DEFAULT 0,
    filter_reason TEXT,
    score         INTEGER,
    skills        REAL,
    experience    REAL,
    location      REAL,
    career_goal   REAL,
    decision      TEXT,
    reasons       TEXT,
    concerns      TEXT,
    model         TEXT,
    scored_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,     -- discover | match | report
    target      TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,     -- running | ok | failed
    jobs_found  INTEGER,
    jobs_new    INTEGER,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS applications (
    job_id     INTEGER PRIMARY KEY REFERENCES jobs(id),
    status     TEXT NOT NULL,
    notes      TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_job ON job_sources(job_id);
CREATE INDEX IF NOT EXISTS idx_matches_score ON matches(score);
"""

_SYNONYMS = [
    (r"\bsr\b", "senior"), (r"\bjr\b", "junior"),
    (r"\bml\b", "machine learning"), (r"\bai\b", "artificial intelligence"),
    (r"\beng\b", "engineer"),
]


def normalize(text: str | None) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    for pattern, repl in _SYNONYMS:
        t = re.sub(pattern, repl, t)
    return re.sub(r"\s+", " ", t).strip()


def dedup_key(company: str, title: str, location: str) -> str:
    return "|".join(normalize(x) for x in (company, title, location))


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def upsert_job(conn: sqlite3.Connection, p: JobPosting) -> tuple[int, bool]:
    """Insert or merge a posting. Returns (canonical job_id, is_new_job)."""
    now = utcnow()

    # Levels 1 & 2: this exact source record was seen before.
    row = conn.execute(
        "SELECT id, job_id FROM job_sources WHERE url = ? OR (source = ? AND source_job_id = ?)",
        (p.url, p.source, p.source_job_id),
    ).fetchone()
    if row:
        conn.execute("UPDATE job_sources SET last_seen = ?, raw_path = COALESCE(?, raw_path) WHERE id = ?",
                     (now, p.raw_path, row["id"]))
        conn.execute(
            "UPDATE jobs SET last_seen = ?, description = CASE WHEN length(?) > length(COALESCE(description, '')) "
            "THEN ? ELSE description END WHERE id = ?",
            (now, p.description, p.description, row["job_id"]),
        )
        return row["job_id"], False

    key = dedup_key(p.company, p.title, p.location)
    remote = None if p.remote is None else int(p.remote)

    # Level 3 (lite): same job found via another source / URL.
    existing = conn.execute("SELECT id FROM jobs WHERE dedup_key = ?", (key,)).fetchone()
    if existing:
        job_id, is_new = existing["id"], False
        conn.execute("UPDATE jobs SET last_seen = ? WHERE id = ?", (now, job_id))
    else:
        cur = conn.execute(
            "INSERT INTO jobs (dedup_key, title, company, location, remote, description, posted_at, "
            "first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, p.title, p.company, p.location, remote, p.description, p.posted_at, now, now),
        )
        job_id, is_new = cur.lastrowid, True

    conn.execute(
        "INSERT INTO job_sources (job_id, source, source_job_id, url, raw_path, search_query, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, p.source, p.source_job_id, p.url, p.raw_path, p.search_query, now, now),
    )
    return job_id, is_new


def jobs_to_match(conn: sqlite3.Connection, profile_hash: str, limit: int | None = None) -> list[sqlite3.Row]:
    """Jobs never evaluated, or evaluated against an older version of the profile."""
    sql = ("SELECT j.* FROM jobs j LEFT JOIN matches m ON m.job_id = j.id "
           "WHERE m.job_id IS NULL OR m.profile_hash != ? ORDER BY j.first_seen DESC")
    params: tuple = (profile_hash,)
    if limit:
        sql += " LIMIT ?"
        params += (limit,)
    return conn.execute(sql, params).fetchall()


def save_filtered(conn: sqlite3.Connection, job_id: int, profile_hash: str, reason: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO matches (job_id, profile_hash, filtered, filter_reason, scored_at) "
        "VALUES (?, ?, 1, ?, ?)",
        (job_id, profile_hash, reason, utcnow()),
    )


def save_match(conn: sqlite3.Connection, job_id: int, profile_hash: str, m: MatchResult, model: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO matches (job_id, profile_hash, filtered, filter_reason, score, skills, experience, "
        "location, career_goal, decision, reasons, concerns, model, scored_at) "
        "VALUES (?, ?, 0, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, profile_hash, m.score, m.skills, m.experience, m.location, m.career_goal, m.decision,
         json.dumps(m.reasons, ensure_ascii=False), json.dumps(m.concerns, ensure_ascii=False), model, utcnow()),
    )


def start_run(conn: sqlite3.Connection, kind: str, target: str | None = None) -> int:
    cur = conn.execute("INSERT INTO runs (kind, target, started_at, status) VALUES (?, ?, ?, 'running')",
                       (kind, target, utcnow()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, found: int | None = None,
               new: int | None = None, error: str | None = None) -> None:
    conn.execute("UPDATE runs SET finished_at = ?, status = ?, jobs_found = ?, jobs_new = ?, error = ? WHERE id = ?",
                 (utcnow(), status, found, new, error, run_id))
    conn.commit()
