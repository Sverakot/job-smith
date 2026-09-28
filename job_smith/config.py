from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
_PATH_FIELDS = ("db_path", "raw_dir", "profile_dir", "reports_dir", "companies_file")


class Settings(BaseModel):
    db_path: Path = Path("data/jobs.db")
    raw_dir: Path = Path("raw")
    profile_dir: Path = Path("data")
    reports_dir: Path = Path("reports")
    companies_file: Path = Path("config/companies.yaml")

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_timeout_s: int = 300
    llm_num_ctx: int = 8192
    max_description_chars: int = 6000

    http_timeout_s: int = 30
    request_delay_s: float = 1.0

    report_min_score: int = 60
    report_top_n: int = 25

    @property
    def profile_json(self) -> Path:
        return self.profile_dir / "profile.json"

    @property
    def profile_md(self) -> Path:
        return self.profile_dir / "profile.md"


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config" / "settings.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    s = Settings(**(data or {}))
    for name in _PATH_FIELDS:
        p = getattr(s, name)
        if not p.is_absolute():
            setattr(s, name, ROOT / p)
    return s
