"""Central configuration. Reads from environment, with sensible defaults.

A tiny dotenv loader is included so the project has no hard dependency on
python-dotenv; if a .env file exists next to the repo root it is loaded once.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root = three levels up from this file (src/petmatch/config.py).
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
WEB_DIR = ROOT / "web"
SITE_DIR = WEB_DIR / "site"
TEMPLATES_DIR = WEB_DIR / "templates"
DB_PATH = DATA_DIR / "petmatch.db"


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE lines). Does not override real env vars."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _b(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # Matching thresholds
    date_window_days: int = _i("PETMATCH_DATE_WINDOW_DAYS", 60)
    date_slack_days: int = _i("PETMATCH_DATE_SLACK_DAYS", 3)
    max_miles: float = _f("PETMATCH_MAX_MILES", 5.0)
    # Stage-1 candidacy for the PHOTO stage: low on purpose -- species match plus
    # plausible geo/date is enough to warrant a photo look (photos do the real
    # disambiguation). attr_score still RANKS which candidates get the budget.
    attr_threshold: float = _f("PETMATCH_ATTR_THRESHOLD", 0.30)
    dash_threshold: float = _f("PETMATCH_DASH_THRESHOLD", 0.45)
    email_threshold: float = _f("PETMATCH_EMAIL_THRESHOLD", 0.75)
    # Cap on confidence when a photo comparison was not possible.
    no_photo_confidence_cap: float = _f("PETMATCH_NO_PHOTO_CAP", 0.6)

    # Vision
    vision_model: str = os.environ.get("PETMATCH_VISION_MODEL", "claude-opus-4-8")
    no_photo: bool = _b("PETMATCH_NO_PHOTO", False)
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    # Max stage-1 survivors to send to vision per run (cost guardrail).
    max_vision_calls: int = _i("PETMATCH_MAX_VISION_CALLS", 200)

    # Scraping
    user_agent: str = os.environ.get(
        "PETMATCH_USER_AGENT",
        "nyc-pet-matcher/0.1 (personal reunite-pets project; contact andyjudlowe@gmail.com)",
    )
    request_delay_s: float = _f("PETMATCH_REQUEST_DELAY_S", 1.0)
    petco_max_pages: int = _i("PETMATCH_PETCO_MAX_PAGES", 40)

    # Email
    email_backend: str = os.environ.get("PETMATCH_EMAIL_BACKEND", "resend")
    report_email: str = os.environ.get("REPORT_EMAIL", "andyjudlowe@gmail.com")
    report_from: str = os.environ.get(
        "REPORT_FROM", "NYC Pet Matcher <onboarding@resend.dev>"
    )
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")
    smtp_host: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = _i("SMTP_PORT", 587)
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_pass: str = os.environ.get("SMTP_PASS", "")

    # Dashboard
    dashboard_url: str = os.environ.get(
        "PETMATCH_DASHBOARD_URL", "https://andyjudlowe.github.io/Hank-Mardukas/"
    )


CONFIG = Config()
