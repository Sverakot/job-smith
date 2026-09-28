from job_smith.filters import hard_filter


def test_passes_relevant_job(profile):
    assert hard_filter(profile, "Machine Learning Engineer", "Tel Aviv-Yafo, Israel", None) is None


def test_ml_does_not_match_html(profile):
    assert hard_filter(profile, "HTML Developer", "Tel Aviv", None) is not None


def test_avoid_keyword(profile):
    assert "sales" in hard_filter(profile, "ML Sales Engineer", "Tel Aviv", None)


def test_too_senior_for_mid(profile):
    assert "seniority" in hard_filter(profile, "Staff ML Engineer", "Israel", None)


def test_location(profile):
    assert "location" in hard_filter(profile, "ML Engineer", "San Francisco, CA", None)
    assert hard_filter(profile, "ML Engineer", "Remote - EMEA", None) is None
    assert hard_filter(profile, "ML Engineer", "", None) is None  # unknown -> LLM decides
