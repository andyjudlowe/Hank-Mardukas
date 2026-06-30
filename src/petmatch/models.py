"""Domain models: unified PetRecord and Match."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Source(str, Enum):
    petco = "petco"
    craigslist = "craigslist"


class Status(str, Enum):
    lost = "lost"
    found = "found"


class Species(str, Enum):
    dog = "dog"
    cat = "cat"
    bird = "bird"
    other = "other"
    unknown = "unknown"


class Sex(str, Enum):
    male = "male"
    female = "female"
    unknown = "unknown"


def make_pet_id(source: Source, source_id: str) -> str:
    """Stable, deterministic id from source + source-native id."""
    raw = f"{source.value}:{source_id}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


class PetRecord(BaseModel):
    id: str
    source: Source
    source_id: str
    status: Status
    species: Species = Species.unknown
    breed: Optional[str] = None
    colors: List[str] = Field(default_factory=list)
    sex: Sex = Sex.unknown
    size: Optional[str] = None  # small | medium | large
    age: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    location_text: Optional[str] = None
    borough: Optional[str] = None
    zip: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    date_reported: Optional[date] = None
    photo_urls: List[str] = Field(default_factory=list)
    detail_url: Optional[str] = None
    contact: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    raw: dict = Field(default_factory=dict)

    @classmethod
    def build(cls, source: Source, source_id: str, **kwargs) -> "PetRecord":
        return cls(id=make_pet_id(source, source_id), source=source,
                   source_id=source_id, **kwargs)


class MatchTier(str, Enum):
    high = "high"
    possible = "possible"
    rejected = "rejected"


class Match(BaseModel):
    lost_id: str
    found_id: str
    attr_score: float
    photo_score: Optional[float] = None
    confidence: float
    tier: MatchTier
    reasons: List[str] = Field(default_factory=list)
    photo_reasoning: Optional[str] = None
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    emailed_at: Optional[datetime] = None

    @property
    def pair_key(self) -> str:
        return f"{self.lost_id}|{self.found_id}"
