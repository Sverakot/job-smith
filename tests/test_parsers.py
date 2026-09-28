from job_smith.textutil import html_to_text
from job_smith.workers.ats_boards import Company, parse_ashby, parse_greenhouse, parse_lever


def test_html_to_text_handles_escaped_html():
    assert html_to_text("&lt;p&gt;Hello &amp;amp; bye&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;") \
        == "Hello & bye\n\n- Python"


def test_greenhouse():
    data = {"jobs": [{"id": 5, "title": " ML Engineer ", "absolute_url": "https://gh/5",
                      "location": {"name": "Tel Aviv"}, "content": "&lt;p&gt;PyTorch&lt;/p&gt;",
                      "updated_at": "2026-09-01T00:00:00Z"}]}
    [j] = parse_greenhouse(data, Company(name="Acme", ats="greenhouse", slug="acme"))
    assert (j.title, j.source_job_id, j.description, j.location) == ("ML Engineer", "5", "PyTorch", "Tel Aviv")


def test_lever():
    data = [{"id": "abc", "text": "Data Scientist", "hostedUrl": "https://lever/abc",
             "categories": {"location": "Remote"}, "descriptionPlain": "Intro",
             "lists": [{"text": "Requirements", "content": "<li>SQL</li>"}], "createdAt": 1756684800000}]
    [j] = parse_lever(data, Company(name="Acme", ats="lever", slug="acme"))
    assert j.remote is True and "SQL" in j.description and j.posted_at.startswith("2025-09-01")


def test_ashby_skips_unlisted():
    data = {"jobs": [{"id": "1", "title": "NLP Engineer", "jobUrl": "https://a/1", "location": "Israel",
                      "isRemote": False, "descriptionPlain": "x"},
                     {"id": "2", "title": "Hidden", "jobUrl": "https://a/2", "isListed": False}]}
    jobs = parse_ashby(data, Company(name="Acme", ats="ashby", slug="acme"))
    assert [j.title for j in jobs] == ["NLP Engineer"]
