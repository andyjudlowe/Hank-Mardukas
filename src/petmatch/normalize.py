"""Shared text -> structured-attribute parsing and geo finalization."""
from __future__ import annotations

import re
from typing import List, Optional

from .geo import borough_from_text, zip_to_borough, zip_to_latlon
from .models import PetRecord, Sex, Species

# Controlled color vocabulary (matched as whole words / common variants).
COLOR_VOCAB = {
    "black": ["black"],
    "white": ["white"],
    "brown": ["brown", "chocolate"],
    "tan": ["tan", "fawn", "buff"],
    "gray": ["gray", "grey", "silver", "blue"],
    "golden": ["golden", "gold", "blonde", "yellow"],
    "cream": ["cream", "ivory"],
    "orange": ["orange", "ginger", "marmalade"],
    "red": ["red", "rust"],
    "brindle": ["brindle"],
    "calico": ["calico"],
    "tabby": ["tabby"],
    "tortoiseshell": ["tortoiseshell", "tortie"],
    "spotted": ["spotted", "spots"],
    "merle": ["merle"],
}

SPECIES_KEYWORDS = {
    Species.dog: ["dog", "puppy", "pup", "canine", "pitbull", "pit bull",
                  "terrier", "shepherd", "chihuahua", "poodle", "retriever",
                  "bulldog", "husky", "beagle", "dachshund", "shih tzu",
                  "yorkie", "labrador", "lab ", "maltese"],
    Species.cat: ["cat", "kitten", "kitty", "feline", "tabby", "calico",
                  "siamese", "tortie", "tortoiseshell"],
    Species.bird: ["bird", "parrot", "parakeet", "cockatiel", "budgie",
                   "macaw", "finch", "cockatoo"],
}

SIZE_KEYWORDS = {
    "small": ["small", "tiny", "toy", "miniature", "mini "],
    "large": ["large", "big", "giant", "xl "],
    "medium": ["medium", "med "],
}

SEX_KEYWORDS = {
    Sex.male: [r"\bmale\b", r"\bboy\b", r"\bneutered\b", r"\bhe\b", r"\bhis\b"],
    Sex.female: [r"\bfemale\b", r"\bgirl\b", r"\bspayed\b", r"\bshe\b", r"\bher\b"],
}

ZIP_RE = re.compile(r"\b(1[01]\d{3})\b")


def detect_species(text: str) -> Species:
    t = text.lower()
    best = Species.unknown
    best_hits = 0
    for sp, kws in SPECIES_KEYWORDS.items():
        hits = sum(1 for k in kws if k in t)
        if hits > best_hits:
            best, best_hits = sp, hits
    return best


def detect_colors(text: str) -> List[str]:
    t = text.lower()
    found = []
    for canonical, variants in COLOR_VOCAB.items():
        if any(re.search(r"\b" + re.escape(v) + r"\b", t) for v in variants):
            found.append(canonical)
    return found


def detect_size(text: str) -> Optional[str]:
    t = text.lower()
    for size, kws in SIZE_KEYWORDS.items():
        if any(k in t for k in kws):
            return size
    return None


def detect_sex(text: str) -> Sex:
    t = text.lower()
    for sex, pats in SEX_KEYWORDS.items():
        if any(re.search(p, t) for p in pats):
            return sex
    return Sex.unknown


def detect_zip(text: str) -> Optional[str]:
    m = ZIP_RE.search(text or "")
    return m.group(1) if m else None


def enrich_from_text(pet: PetRecord) -> PetRecord:
    """Fill missing structured fields by parsing name/breed/description/location."""
    blob = " ".join(filter(None, [pet.name, pet.breed, pet.description,
                                  pet.location_text]))
    if pet.species in (Species.unknown, None):
        pet.species = detect_species(blob)
    if not pet.colors:
        pet.colors = detect_colors(blob)
    if not pet.size:
        pet.size = detect_size(blob)
    if pet.sex in (Sex.unknown, None):
        pet.sex = detect_sex(blob)
    if not pet.zip:
        pet.zip = detect_zip(blob)
    return finalize_geo(pet)


def finalize_geo(pet: PetRecord) -> PetRecord:
    """Resolve borough and lat/lon from zip and/or location text (offline)."""
    if not pet.borough:
        pet.borough = (zip_to_borough(pet.zip)
                       or borough_from_text(pet.location_text)
                       or borough_from_text(pet.description))
    if pet.lat is None or pet.lon is None:
        coords = zip_to_latlon(pet.zip)
        if coords:
            pet.lat, pet.lon = coords
    return pet
