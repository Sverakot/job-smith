"""Discovery worker for public ATS job-board APIs (Greenhouse, Lever, Ashby).

These endpoints are published by the ATS vendors for exactly this purpose (embedding job
boards), return JSON, and need no login. The worker only captures data; it never judges fit.
"""
import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel

from .. import db
from ..config import Settings
from ..models import JobPosting
from ..textutil import html_to_text

log = logging.getLogger(__name__)

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


class Company(BaseModel):
    name: str
    ats: Literal["greenhouse", "lever", "ashby"]
    slug: str


def load_companies(path: Path) -> list[Company]:
    data = yaml.safe_load(path.read_text()) or {}
    return [Company(**c) for c in data.get("companies") or []]


# ---------- pure parsers (unit-testable, no network) ----------

def parse_greenhouse(data: dict, c: Company, raw_path: str | None = None) -> list[JobPosting]:
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(JobPosting(
            source="greenhouse", source_job_id=str(j["id"]), url=j["absolute_url"],
            title=j["title"].strip(), company=c.name, location=loc,
            remote=("remote" in loc.lower()) or None,
            description=html_to_text(j.get("content")),
            posted_at=j.get("first_published") or j.get("updated_at"),
            raw_path=raw_path, search_query=f"greenhouse:{c.slug}",
        ))
    return out


def parse_lever(data: list, c: Company, raw_path: str | None = None) -> list[JobPosting]:
    out = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
        parts.append(j.get("additionalPlain") or "")
        created = j.get("createdAt")
        out.append(JobPosting(
            source="lever", source_job_id=j["id"], url=j["hostedUrl"],
            title=j["text"].strip(), company=c.name, location=loc or "",
            remote=(j.get("workplaceType") == "remote") or ("remote" in (loc or "").lower()) or None,
            description="\n\n".join(p for p in parts if p).strip(),
            posted_at=datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if created else None,
            raw_path=raw_path, search_query=f"lever:{c.slug}",
        ))
    return out


def parse_ashby(data: dict, c: Company, raw_path: str | None = None) -> list[JobPosting]:
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        loc = "; ".join(x for x in locs if x)
        out.append(JobPosting(
            source="ashby", source_job_id=str(j["id"]), url=j.get("jobUrl") or j.get("applyUrl"),
            title=j["title"].strip(), company=c.name, location=loc,
            remote=j.get("isRemote") or (j.get("workplaceType") == "Remote") or None,
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            posted_at=j.get("publishedAt"),
            raw_path=raw_path, search_query=f"ashby:{c.slug}",
        ))
    return out


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}


# ---------- network + orchestration ----------

def fetch_company(client: httpx.Client, c: Company, raw_dir: Path) -> list[JobPosting]:
    resp = client.get(ENDPOINTS[c.ats].format(slug=c.slug))
    resp.raise_for_status()
    data = resp.json()
    raw_path = raw_dir / c.ats / c.slug / f"{date.today().isoformat()}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(data, ensure_ascii=False))
    return PARSERS[c.ats](data, c, str(raw_path))


def discover(settings: Settings, conn) -> dict:
    companies = load_companies(settings.companies_file)
    if not companies:
        log.warning("No companies in %s", settings.companies_file)
    stats = {"companies": len(companies), "failed": 0, "found": 0, "new": 0}
    headers = {"User-Agent": "job-smith/0.1 (personal job search)"}

    with httpx.Client(timeout=settings.http_timeout_s, headers=headers, follow_redirects=True) as client:
        for c in companies:
            run_id = db.start_run(conn, "discover", f"{c.ats}:{c.slug}")
            try:
                postings = fetch_company(client, c, settings.raw_dir)
                new = sum(db.upsert_job(conn, p)[1] for p in postings)
                conn.commit()
                db.finish_run(conn, run_id, "ok", len(postings), new)
                stats["found"] += len(postings)
                stats["new"] += new
                log.info("%-20s %4d jobs (%d new)", c.name, len(postings), new)
            except Exception as e:  # one broken source must not stop the run
                conn.rollback()
                db.finish_run(conn, run_id, "failed", error=repr(e)[:500])
                stats["failed"] += 1
                log.error("%-20s FAILED: %s", c.name, e)
            time.sleep(settings.request_delay_s)
    return stats
