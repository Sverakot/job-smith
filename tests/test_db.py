from job_smith import db
from job_smith.models import JobPosting


def posting(**kw):
    base = dict(source="greenhouse", source_job_id="1", url="https://x/1", title="ML Engineer",
                company="Acme", location="Tel Aviv, Israel", description="short")
    return JobPosting(**{**base, **kw})


def test_same_source_record_is_merged(conn):
    a, new_a = db.upsert_job(conn, posting())
    b, new_b = db.upsert_job(conn, posting(description="a much longer description"))
    assert a == b and new_a and not new_b
    assert conn.execute("SELECT description FROM jobs").fetchone()[0] == "a much longer description"


def test_same_job_other_source_becomes_one_canonical_job(conn):
    a, _ = db.upsert_job(conn, posting())
    b, new = db.upsert_job(conn, posting(source="lever", source_job_id="zz", url="https://y/zz",
                                         title="Machine Learning Engineer", company="ACME"))
    assert a == b and not new
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0] == 2


def test_different_jobs_stay_separate(conn):
    db.upsert_job(conn, posting())
    db.upsert_job(conn, posting(source_job_id="2", url="https://x/2", title="Data Scientist"))
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
