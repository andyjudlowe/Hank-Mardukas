"""Build view-models for matches and render the weekly email digest."""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import CONFIG, TEMPLATES_DIR, Config
from .models import Match, PetRecord
from .storage import get_unemailed_high_matches, pets_by_id


def _pet_view(pet: Optional[PetRecord]) -> dict:
    if pet is None:
        return {"missing": True}
    return {
        "missing": False,
        "name": pet.name or "Unknown",
        "species": pet.species.value,
        "breed": pet.breed,
        "colors": pet.colors,
        "sex": pet.sex.value,
        "borough": pet.borough or "Unknown area",
        "location_text": pet.location_text,
        "date": pet.date_reported.isoformat() if pet.date_reported else None,
        "photo": pet.photo_urls[0] if pet.photo_urls else None,
        "detail_url": pet.detail_url,
        "source": pet.source.value,
    }


def build_match_view(m: Match, pets: Dict[str, PetRecord]) -> dict:
    return {
        "lost": _pet_view(pets.get(m.lost_id)),
        "found": _pet_view(pets.get(m.found_id)),
        "confidence": round(m.confidence * 100),
        "attr_score": round(m.attr_score * 100),
        "photo_score": round(m.photo_score * 100) if m.photo_score is not None else None,
        "tier": m.tier.value,
        "reasons": m.reasons,
    }


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )


def render_email(matches: List[Match], pets: Dict[str, PetRecord],
                 cfg: Config = CONFIG) -> tuple:
    """Return (subject, html, text) for the weekly digest."""
    views = [build_match_view(m, pets) for m in matches]
    n = len(views)
    subject = (f"🐾 NYC Pet Matcher: {n} new likely match{'es' if n != 1 else ''}"
               if n else "🐾 NYC Pet Matcher: no new matches this week")
    html = _env().get_template("email.html.j2").render(
        matches=views, count=n, dashboard_url=cfg.dashboard_url)

    lines = [subject, ""]
    for v in views:
        lines.append(f"[{v['confidence']}%] LOST {v['lost'].get('name')} "
                     f"({v['lost'].get('borough')}) <-> FOUND "
                     f"{v['found'].get('name')} ({v['found'].get('borough')})")
        lines.append(f"   lost:  {v['lost'].get('detail_url')}")
        lines.append(f"   found: {v['found'].get('detail_url')}")
        lines.append(f"   why: {', '.join(v['reasons'])}")
        lines.append("")
    lines.append(f"More possible matches: {cfg.dashboard_url}")
    return subject, html, "\n".join(lines)


def weekly_digest(conn: sqlite3.Connection, cfg: Config = CONFIG) -> tuple:
    """Gather unemailed high-confidence matches and render the digest."""
    matches = get_unemailed_high_matches(conn)
    pets = pets_by_id(conn)
    subject, html, text = render_email(matches, pets, cfg)
    return matches, subject, html, text
