"""End-to-end: discovered jobs -> match (with a fake LLM) -> report."""
from job_smith import db
from job_smith.agents import matcher
from job_smith.models import JobPosting, MatchResult
from job_smith.report import build_report


def test_match_and_report(settings, conn, profile, monkeypatch):
    settings.profile_json.write_text(profile.model_dump_json())
    for i, (title, loc) in enumerate([("ML Engineer", "Tel Aviv"), ("Sales Manager", "Tel Aviv"),
                                      ("NLP Engineer", "Berlin")]):
        db.upsert_job(conn, JobPosting(source="greenhouse", source_job_id=str(i), url=f"https://x/{i}",
                                       title=title, company="Acme", location=loc, description="PyTorch"))
    conn.commit()

    calls = []

    def fake_llm(settings, system, user, cls, retries=2):
        calls.append(user)
        return MatchResult(score=91, skills=0.9, experience=0.8, location=1, career_goal=0.9,
                           decision="strong_match", reasons=["PyTorch required"], concerns=[])

    monkeypatch.setattr(matcher, "structured", fake_llm)
    stats = matcher.match(settings, conn)
    assert stats == {"pending": 3, "filtered": 2, "scored": 1, "errors": 0}
    assert len(calls) == 1

    # Nothing left to do on a second run; profile change triggers re-evaluation.
    assert matcher.match(settings, conn)["pending"] == 0
    settings.profile_json.write_text(profile.model_copy(update={"locations": ["Tel Aviv", "Israel", "Berlin"]}).model_dump_json())
    assert matcher.match(settings, conn)["pending"] == 3

    text = build_report(settings, conn).read_text()
    assert "ML Engineer — Acme" in text and "Score: 91/100" in text and "https://x/0" in text
