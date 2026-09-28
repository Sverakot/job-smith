"""Cheap rule-based filters applied before the LLM, so the local model only sees plausible jobs."""
import re

from .models import Profile

TOO_SENIOR = ["staff", "principal", "director", "head of", "vp", "vice president", "chief", "distinguished"]
TOO_JUNIOR = ["intern", "internship", "student", "graduate program"]


def _contains(text: str, fragment: str) -> bool:
    """Fragment match anchored at a word start: 'ml' matches 'ML Engineer' but not 'HTML'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(fragment.lower()), text.lower()) is not None


def hard_filter(profile: Profile, title: str, location: str | None, remote: int | None) -> str | None:
    """Return a rejection reason, or None if the job should go to the LLM."""
    for kw in profile.avoid_keywords:
        if _contains(title, kw):
            return f"title contains avoided keyword '{kw}'"

    if profile.title_keywords and not any(_contains(title, kw) for kw in profile.title_keywords):
        return "title matches none of title_keywords"

    if profile.seniority in ("junior", "mid"):
        for kw in TOO_SENIOR:
            if _contains(title, kw):
                return f"seniority: '{kw}' role"
    if profile.seniority in ("mid", "senior", "staff"):
        for kw in TOO_JUNIOR:
            if _contains(title, kw):
                return f"seniority: '{kw}' role"

    loc = (location or "").lower()
    if loc:  # unknown location -> let the LLM decide
        in_area = any(p.lower() in loc for p in profile.locations)
        is_remote = bool(remote) or "remote" in loc
        if not in_area and not (profile.remote_ok and is_remote):
            return f"location '{location}' not in {profile.locations}"
    return None
