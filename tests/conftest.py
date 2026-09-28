import pytest

from job_smith import db
from job_smith.config import Settings
from job_smith.models import Profile


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "jobs.db", raw_dir=tmp_path / "raw", profile_dir=tmp_path,
                    reports_dir=tmp_path / "reports", companies_file=tmp_path / "companies.yaml",
                    request_delay_s=0)


@pytest.fixture
def conn(settings):
    c = db.connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def profile():
    return Profile(
        summary="ML engineer, NLP focus.", target_titles=["ML Engineer", "Data Scientist"],
        title_keywords=["machine learning", "ml", "data scien", "nlp"], locations=["Tel Aviv", "Israel"],
        years_experience=2, seniority="mid", domains=["NLP"], skills_strong=["Python", "PyTorch"],
        avoid_keywords=["sales", "frontend"],
    )
