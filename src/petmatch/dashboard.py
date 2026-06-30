"""Generate the static, public, link-back-only dashboard into web/site/.

Two pages: possible/edge-case matches (the focus) and stats & trends. Match cards
deep-link to the original posts and deliberately omit contact info.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import CONFIG, SITE_DIR, TEMPLATES_DIR, WEB_DIR, Config
from .models import MatchTier, Status
from .report import build_match_view
from .storage import get_matches, get_pets, get_runs, pets_by_id


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )


def compute_stats(conn: sqlite3.Connection) -> dict:
    lost = get_pets(conn, Status.lost)
    found = get_pets(conn, Status.found)
    high = get_matches(conn, MatchTier.high)
    possible = get_matches(conn, MatchTier.possible)

    def borough_counts(pets):
        c = Counter((p.borough or "Unknown") for p in pets)
        return [{"label": k, "value": v} for k, v in c.most_common()]

    def species_counts(pets):
        c = Counter(p.species.value for p in pets)
        return [{"label": k, "value": v} for k, v in c.most_common()]

    runs = list(reversed(get_runs(conn, limit=40)))  # oldest -> newest
    trend = [{
        "date": (r.get("finished_at") or r.get("started_at") or "")[:10],
        "pets": r.get("pets_scraped") or 0,
        "high": r.get("matches_high") or 0,
        "possible": r.get("matches_possible") or 0,
    } for r in runs]

    return {
        "totals": {
            "lost": len(lost), "found": len(found),
            "high": len(high), "possible": len(possible),
        },
        "lost_by_borough": borough_counts(lost),
        "found_by_borough": borough_counts(found),
        "lost_by_species": species_counts(lost),
        "found_by_species": species_counts(found),
        "trend": trend,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def build_site(conn: sqlite3.Connection, cfg: Config = CONFIG) -> dict:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    pets = pets_by_id(conn)

    # Dashboard shows everything not rejected: possible (focus) + high.
    matches = (get_matches(conn, MatchTier.high)
               + get_matches(conn, MatchTier.possible))
    matches.sort(key=lambda m: m.confidence, reverse=True)
    views = [build_match_view(m, pets) for m in matches]

    stats = compute_stats(conn)
    env = _env()
    generated_at = stats["generated_at"]

    (SITE_DIR / "index.html").write_text(
        env.get_template("dashboard.html.j2").render(
            matches=views, count=len(views), stats=stats,
            generated_at=generated_at, dashboard_url=cfg.dashboard_url),
        encoding="utf-8")
    (SITE_DIR / "stats.html").write_text(
        env.get_template("stats.html.j2").render(
            stats=stats, generated_at=generated_at),
        encoding="utf-8")
    (SITE_DIR / "matches.json").write_text(
        json.dumps(views, indent=2), encoding="utf-8")
    (SITE_DIR / "stats.json").write_text(
        json.dumps(stats, indent=2), encoding="utf-8")

    # copy static assets
    assets_src = WEB_DIR / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, SITE_DIR / "assets", dirs_exist_ok=True)

    print(f"  dashboard: {len(views)} match cards -> {SITE_DIR}")
    return {"cards": len(views)}


if __name__ == "__main__":  # python -m petmatch.dashboard
    from .storage import connect
    conn = connect()
    try:
        build_site(conn)
    finally:
        conn.close()
