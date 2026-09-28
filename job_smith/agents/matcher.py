"""Evaluation agent: hard filters first, then LLM scoring for jobs that pass."""
import hashlib
import logging

from .. import db
from ..config import Settings
from ..filters import hard_filter
from ..llm import LLMError, structured
from ..models import MatchResult, Profile
from .profile import load_profile

log = logging.getLogger(__name__)

SYSTEM = """You are a strict technical recruiter evaluating how well ONE job fits ONE candidate.
Scoring guide for `score`:
  90-100 apply today: title, level, core skills and location all fit
  75-89  good fit with minor gaps
  60-74  plausible, notable gaps or unknowns
  40-59  weak fit
  0-39   wrong role, level or location
decision: strong_match (>=85), match (70-84), weak_match (50-69), reject (<50).
Sub-scores are 0.0-1.0. Base every reason and concern on the job text.
Do not assume salary, visa or remote policy if the text does not state them; list them as concerns instead."""


def profile_hash(profile: Profile) -> str:
    return hashlib.sha256(profile.model_dump_json().encode()).hexdigest()[:16]


def _job_prompt(profile: Profile, job, max_chars: int) -> str:
    desc = (job["description"] or "")[:max_chars]
    return (f"CANDIDATE PROFILE (JSON):\n{profile.model_dump_json(indent=1)}\n\n"
            f"JOB:\nTitle: {job['title']}\nCompany: {job['company']}\n"
            f"Location: {job['location'] or 'not stated'}\n\nDescription:\n{desc}")


def match(settings: Settings, conn, limit: int | None = None, rescore: bool = False) -> dict:
    profile = load_profile(settings)
    phash = profile_hash(profile)
    if rescore:  # e.g. after changing the model or the prompt
        conn.execute("UPDATE matches SET profile_hash = 'stale'")
        conn.commit()

    jobs = db.jobs_to_match(conn, phash, limit)
    stats = {"pending": len(jobs), "filtered": 0, "scored": 0, "errors": 0}
    run_id = db.start_run(conn, "match")
    log.info("%d jobs to evaluate", len(jobs))

    for i, job in enumerate(jobs, 1):
        reason = hard_filter(profile, job["title"], job["location"], job["remote"])
        if reason:
            db.save_filtered(conn, job["id"], phash, reason)
            conn.commit()
            stats["filtered"] += 1
            continue
        try:
            result = structured(settings, SYSTEM, _job_prompt(profile, job, settings.max_description_chars),
                                MatchResult)
        except LLMError as e:
            stats["errors"] += 1
            log.error("[%d/%d] %s @ %s: %s", i, len(jobs), job["title"], job["company"], e)
            if "request failed" in str(e):  # Ollama is down: stop instead of failing every job
                db.finish_run(conn, run_id, "failed", error=str(e)[:500])
                raise
            continue
        db.save_match(conn, job["id"], phash, result, settings.ollama_model)
        conn.commit()
        stats["scored"] += 1
        log.info("[%d/%d] %3d  %s @ %s", i, len(jobs), result.score, job["title"], job["company"])

    db.finish_run(conn, run_id, "ok", stats["pending"], stats["scored"])
    return stats
