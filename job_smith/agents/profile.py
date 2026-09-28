"""Profile agent: CV -> profile.json (for machines) + profile.md (for you and the LLM)."""
import logging
from pathlib import Path

from ..config import Settings
from ..llm import structured
from ..models import Profile

log = logging.getLogger(__name__)

SYSTEM = """You extract a structured job-search profile from a candidate's CV.
Rules:
- Use only facts present in the CV or in the stated preferences. Do not invent skills or experience.
- years_experience: professional experience only (exclude pure study), estimated from dates.
- seniority: junior (<2y), mid (2-5y), senior (5-9y), staff (9y+), adjusted by responsibilities.
- skills_strong: used substantially in jobs/projects. skills_moderate: mentioned or used briefly.
- title_keywords: short lowercase fragments that relevant job titles would contain.
- avoid_keywords: lowercase fragments for clearly unsuitable job titles (from preferences, plus obvious ones).
- If a preference is not stated, use the schema default."""


def read_cv(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported CV format '{suffix}'. Use PDF, TXT or MD (export .docx to PDF first).")


def render_markdown(p: Profile) -> str:
    def bullets(items):
        return "\n".join(f"- {x}" for x in items) or "- (none)"
    return f"""# Candidate Profile

{p.summary}

## Targets
{bullets(p.target_titles)}

## Experience
{p.years_experience:g} years, {p.seniority} level. Domains: {', '.join(p.domains) or '-'}

## Skills
Strong: {', '.join(p.skills_strong) or '-'}
Moderate: {', '.join(p.skills_moderate) or '-'}

## Constraints
- Locations: {', '.join(p.locations)}
- Remote OK: {p.remote_ok} / Hybrid OK: {p.hybrid_ok}
- Employment: {', '.join(p.employment_types)}
- Minimum salary: {p.salary_min or 'not specified'}
- Avoid: {', '.join(p.avoid_keywords) or '-'}
"""


def build_profile(settings: Settings, cv_path: Path, preferences: str = "", force: bool = False) -> Profile:
    if settings.profile_json.exists() and not force:
        raise FileExistsError(f"{settings.profile_json} exists (you may have edited it). Use --force to overwrite.")
    cv_text = read_cv(cv_path)
    if len(cv_text.strip()) < 200:
        log.warning("CV text is very short (%d chars); is the PDF scanned/image-only?", len(cv_text))

    user = f"CV:\n\"\"\"\n{cv_text}\n\"\"\"\n\nStated preferences:\n{preferences or '(none)'}"
    profile = structured(settings, SYSTEM, user, Profile)

    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    settings.profile_json.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    settings.profile_md.write_text(render_markdown(profile), encoding="utf-8")
    return profile


def load_profile(settings: Settings) -> Profile:
    if not settings.profile_json.exists():
        raise FileNotFoundError(f"No profile at {settings.profile_json}. Run: job-smith profile <cv.pdf>")
    return Profile.model_validate_json(settings.profile_json.read_text(encoding="utf-8"))
