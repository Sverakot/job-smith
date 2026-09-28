"""Schemas shared by agents, workers and the database layer."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Profile(BaseModel):
    """Structured candidate profile. Generated from the CV, then edited by hand."""
    summary: str = Field(description="2-4 sentence summary of the candidate and what they are looking for")
    target_titles: list[str] = Field(description="Job titles to search for, most preferred first")
    title_keywords: list[str] = Field(
        default_factory=list,
        description="Lowercase fragments; a job title must contain at least one to be considered, "
                    "e.g. 'machine learning', 'ml', 'data scien', 'nlp'",
    )
    locations: list[str] = Field(description="Acceptable locations, e.g. 'Tel Aviv', 'Israel'")
    remote_ok: bool = True
    hybrid_ok: bool = True
    years_experience: float
    seniority: Literal["junior", "mid", "senior", "staff"]
    domains: list[str] = Field(description="Domains of expertise, e.g. 'NLP', 'computer vision'")
    skills_strong: list[str]
    skills_moderate: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list, description="Spoken languages")
    employment_types: list[str] = Field(default_factory=lambda: ["full-time"])
    salary_min: int | None = None
    avoid_keywords: list[str] = Field(
        default_factory=list,
        description="Lowercase fragments; jobs whose title contains any of these are rejected",
    )


class JobPosting(BaseModel):
    """One job as found at one source. Workers only produce these; they never judge fit."""
    source: str
    source_job_id: str
    url: str
    title: str
    company: str
    location: str = ""
    remote: bool | None = None
    description: str = ""
    posted_at: str | None = None
    raw_path: str | None = None
    search_query: str | None = None


class MatchResult(BaseModel):
    """LLM evaluation of one job against the profile."""
    score: int = Field(ge=0, le=100, description="Overall fit 0-100")
    skills: float = Field(ge=0, le=1)
    experience: float = Field(ge=0, le=1)
    location: float = Field(ge=0, le=1)
    career_goal: float = Field(ge=0, le=1)
    decision: Literal["strong_match", "match", "weak_match", "reject"]
    reasons: list[str] = Field(description="Why it fits; concrete, cite the job text")
    concerns: list[str] = Field(description="Gaps, missing requirements, unknowns")
