"""SQLite persistence layer."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from .config import DB_PATH
from .models import Match, MatchTier, PetRecord, Sex, Source, Species, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS pets (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL,
    species TEXT,
    breed TEXT,
    colors TEXT,
    sex TEXT,
    size TEXT,
    age TEXT,
    name TEXT,
    description TEXT,
    location_text TEXT,
    borough TEXT,
    zip TEXT,
    lat REAL,
    lon REAL,
    date_reported TEXT,
    photo_urls TEXT,
    detail_url TEXT,
    contact TEXT,
    scraped_at TEXT,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_pets_status ON pets(status);
CREATE INDEX IF NOT EXISTS idx_pets_species ON pets(species);

CREATE TABLE IF NOT EXISTS matches (
    lost_id TEXT NOT NULL,
    found_id TEXT NOT NULL,
    attr_score REAL,
    photo_score REAL,
    confidence REAL,
    tier TEXT,
    reasons TEXT,
    photo_reasoning TEXT,
    first_seen TEXT,
    emailed_at TEXT,
    dismissed INTEGER DEFAULT 0,
    PRIMARY KEY (lost_id, found_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_tier ON matches(tier);

CREATE TABLE IF NOT EXISTS photo_cache (
    key TEXT PRIMARY KEY,
    score REAL,
    reasoning TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    finished_at TEXT,
    pets_scraped INTEGER,
    matches_total INTEGER,
    matches_high INTEGER,
    matches_possible INTEGER,
    emailed INTEGER,
    note TEXT
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------------- pets ----------------

def upsert_pet(conn: sqlite3.Connection, pet: PetRecord) -> None:
    conn.execute(
        """
        INSERT INTO pets (id, source, source_id, status, species, breed, colors,
            sex, size, age, name, description, location_text, borough, zip, lat,
            lon, date_reported, photo_urls, detail_url, contact, scraped_at, raw)
        VALUES (:id, :source, :source_id, :status, :species, :breed, :colors,
            :sex, :size, :age, :name, :description, :location_text, :borough, :zip,
            :lat, :lon, :date_reported, :photo_urls, :detail_url, :contact,
            :scraped_at, :raw)
        ON CONFLICT(id) DO UPDATE SET
            status=excluded.status, species=excluded.species, breed=excluded.breed,
            colors=excluded.colors, sex=excluded.sex, size=excluded.size,
            age=excluded.age, name=excluded.name, description=excluded.description,
            location_text=excluded.location_text, borough=excluded.borough,
            zip=excluded.zip, lat=excluded.lat, lon=excluded.lon,
            date_reported=excluded.date_reported, photo_urls=excluded.photo_urls,
            detail_url=excluded.detail_url, contact=excluded.contact,
            scraped_at=excluded.scraped_at, raw=excluded.raw
        """,
        {
            "id": pet.id,
            "source": pet.source.value,
            "source_id": pet.source_id,
            "status": pet.status.value,
            "species": pet.species.value,
            "breed": pet.breed,
            "colors": json.dumps(pet.colors),
            "sex": pet.sex.value,
            "size": pet.size,
            "age": pet.age,
            "name": pet.name,
            "description": pet.description,
            "location_text": pet.location_text,
            "borough": pet.borough,
            "zip": pet.zip,
            "lat": pet.lat,
            "lon": pet.lon,
            "date_reported": pet.date_reported.isoformat() if pet.date_reported else None,
            "photo_urls": json.dumps(pet.photo_urls),
            "detail_url": pet.detail_url,
            "contact": pet.contact,
            "scraped_at": pet.scraped_at.isoformat(),
            "raw": json.dumps(pet.raw),
        },
    )


def _row_to_pet(row: sqlite3.Row) -> PetRecord:
    d = dict(row)
    return PetRecord(
        id=d["id"],
        source=Source(d["source"]),
        source_id=d["source_id"],
        status=Status(d["status"]),
        species=Species(d["species"]) if d["species"] else Species.unknown,
        breed=d["breed"],
        colors=json.loads(d["colors"]) if d["colors"] else [],
        sex=Sex(d["sex"]) if d["sex"] else Sex.unknown,
        size=d["size"],
        age=d["age"],
        name=d["name"],
        description=d["description"],
        location_text=d["location_text"],
        borough=d["borough"],
        zip=d["zip"],
        lat=d["lat"],
        lon=d["lon"],
        date_reported=date.fromisoformat(d["date_reported"]) if d["date_reported"] else None,
        photo_urls=json.loads(d["photo_urls"]) if d["photo_urls"] else [],
        detail_url=d["detail_url"],
        contact=d["contact"],
        scraped_at=datetime.fromisoformat(d["scraped_at"]) if d["scraped_at"] else datetime.utcnow(),
        raw=json.loads(d["raw"]) if d["raw"] else {},
    )


def get_pets(conn: sqlite3.Connection, status: Optional[Status] = None) -> List[PetRecord]:
    if status:
        rows = conn.execute("SELECT * FROM pets WHERE status=?", (status.value,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pets").fetchall()
    return [_row_to_pet(r) for r in rows]


def get_pet(conn: sqlite3.Connection, pet_id: str) -> Optional[PetRecord]:
    row = conn.execute("SELECT * FROM pets WHERE id=?", (pet_id,)).fetchone()
    return _row_to_pet(row) if row else None


def pets_by_id(conn: sqlite3.Connection) -> Dict[str, PetRecord]:
    return {p.id: p for p in get_pets(conn)}


def existing_pet_ids(conn: sqlite3.Connection, source: Source) -> set:
    rows = conn.execute("SELECT id FROM pets WHERE source=?", (source.value,)).fetchall()
    return {r["id"] for r in rows}


# ---------------- matches ----------------

def upsert_match(conn: sqlite3.Connection, m: Match) -> None:
    """Insert or update a match, preserving emailed_at/dismissed if already set."""
    conn.execute(
        """
        INSERT INTO matches (lost_id, found_id, attr_score, photo_score, confidence,
            tier, reasons, photo_reasoning, first_seen, emailed_at, dismissed)
        VALUES (:lost_id, :found_id, :attr_score, :photo_score, :confidence, :tier,
            :reasons, :photo_reasoning, :first_seen, NULL, 0)
        ON CONFLICT(lost_id, found_id) DO UPDATE SET
            attr_score=excluded.attr_score, photo_score=excluded.photo_score,
            confidence=excluded.confidence, tier=excluded.tier,
            reasons=excluded.reasons, photo_reasoning=excluded.photo_reasoning
        """,
        {
            "lost_id": m.lost_id,
            "found_id": m.found_id,
            "attr_score": m.attr_score,
            "photo_score": m.photo_score,
            "confidence": m.confidence,
            "tier": m.tier.value,
            "reasons": json.dumps(m.reasons),
            "photo_reasoning": m.photo_reasoning,
            "first_seen": m.first_seen.isoformat(),
        },
    )


def _row_to_match(row: sqlite3.Row) -> Match:
    d = dict(row)
    return Match(
        lost_id=d["lost_id"],
        found_id=d["found_id"],
        attr_score=d["attr_score"],
        photo_score=d["photo_score"],
        confidence=d["confidence"],
        tier=MatchTier(d["tier"]),
        reasons=json.loads(d["reasons"]) if d["reasons"] else [],
        photo_reasoning=d["photo_reasoning"],
        first_seen=datetime.fromisoformat(d["first_seen"]) if d["first_seen"] else datetime.utcnow(),
        emailed_at=datetime.fromisoformat(d["emailed_at"]) if d["emailed_at"] else None,
    )


def get_matches(conn: sqlite3.Connection, tier: Optional[MatchTier] = None,
                include_dismissed: bool = False) -> List[Match]:
    q = "SELECT * FROM matches WHERE 1=1"
    params: list = []
    if tier:
        q += " AND tier=?"
        params.append(tier.value)
    if not include_dismissed:
        q += " AND dismissed=0"
    q += " ORDER BY confidence DESC"
    rows = conn.execute(q, params).fetchall()
    return [_row_to_match(r) for r in rows]


def get_unemailed_high_matches(conn: sqlite3.Connection) -> List[Match]:
    rows = conn.execute(
        "SELECT * FROM matches WHERE tier=? AND emailed_at IS NULL AND dismissed=0 "
        "ORDER BY confidence DESC",
        (MatchTier.high.value,),
    ).fetchall()
    return [_row_to_match(r) for r in rows]


def mark_emailed(conn: sqlite3.Connection, matches: List[Match]) -> None:
    now = datetime.utcnow().isoformat()
    conn.executemany(
        "UPDATE matches SET emailed_at=? WHERE lost_id=? AND found_id=?",
        [(now, m.lost_id, m.found_id) for m in matches],
    )


# ---------------- photo cache ----------------

def photo_cache_get(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT score, reasoning FROM photo_cache WHERE key=?", (key,)).fetchone()
    if row:
        return row["score"], row["reasoning"]
    return None


def photo_cache_put(conn: sqlite3.Connection, key: str, score: float, reasoning: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO photo_cache (key, score, reasoning, created_at) "
        "VALUES (?, ?, ?, ?)",
        (key, score, reasoning, datetime.utcnow().isoformat()),
    )


# ---------------- runs ----------------

def record_run(conn: sqlite3.Connection, **fields) -> None:
    conn.execute(
        "INSERT INTO runs (started_at, finished_at, pets_scraped, matches_total, "
        "matches_high, matches_possible, emailed, note) VALUES (?,?,?,?,?,?,?,?)",
        (
            fields.get("started_at"),
            fields.get("finished_at"),
            fields.get("pets_scraped", 0),
            fields.get("matches_total", 0),
            fields.get("matches_high", 0),
            fields.get("matches_possible", 0),
            fields.get("emailed", 0),
            fields.get("note", ""),
        ),
    )


def get_runs(conn: sqlite3.Connection, limit: int = 60) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
