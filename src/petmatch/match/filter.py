"""Stage 1: attribute hard-gates + weighted similarity score.

Cheap and runs on every lost x found pair. Hard gates eliminate impossible pairs
(different species, impossible dates, non-adjacent boroughs). Survivors get an
attribute similarity score in [0, 1] used to rank candidates for the photo stage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional

from ..config import Config
from ..geo import boroughs_adjacent, haversine_miles
from ..models import PetRecord, Sex, Species

# Base colors are common enough among NYC pets (a large share of cats and dogs
# are "black" or "brown") that sharing just one isn't real evidence on its
# own. Pattern/coat colors are far more identifying.
_DISTINCTIVE_COLORS = {"brindle", "calico", "tabby", "tortoiseshell", "spotted", "merle"}

# Breed-text filler that shows up on almost every cat/dog listing and isn't a
# real breed signal -- "Domestic Shorthair Mix" overlapping "Domestic
# Shorthair" says nothing about whether it's the same animal.
_GENERIC_BREED_WORDS = {
    "mix", "mixed", "domestic", "shorthair", "longhair", "short", "long",
    "hair", "haired", "unknown", "various", "breed", "kitten", "puppy",
}

# Boilerplate lost/found posting language. SequenceMatcher's character-level
# ratio gets inflated by shared phrases like "near the park, very friendly"
# even between totally unrelated pets, so corroboration from free text
# instead requires shared *content* words once this filler is stripped out.
_TEXT_STOPWORDS = {
    "lost", "found", "dog", "cat", "puppy", "kitten", "pet", "near", "park",
    "street", "avenue", "seen", "last", "very", "friendly", "please",
    "contact", "call", "email", "reward", "missing", "seems", "seem",
    "looks", "look", "like", "good", "sweet", "scared", "afraid", "nice",
    "loving", "home", "area", "around", "today", "yesterday", "morning",
    "evening", "afternoon", "night", "help", "anyone", "know",
    "information", "info", "thanks", "thank", "the", "and", "with", "this",
    "that", "was", "has", "have", "had", "for", "from", "named", "name",
}


@dataclass
class AttrResult:
    passed: bool
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    miles: Optional[float] = None
    days_apart: Optional[int] = None
    # True when a distinguishing attribute (color/breed/free-text) actually
    # overlaps -- i.e. there's more than just "same species, same area".
    corroborated: bool = False


def _tokens(s: Optional[str]) -> set:
    if not s:
        return set()
    return {t for t in "".join(c if c.isalnum() else " " for c in s.lower()).split()
            if len(t) > 2}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _distance_miles(lost: PetRecord, found: PetRecord) -> Optional[float]:
    if None in (lost.lat, lost.lon, found.lat, found.lon):
        return None
    return haversine_miles(lost.lat, lost.lon, found.lat, found.lon)


def stage1(lost: PetRecord, found: PetRecord, cfg: Config) -> AttrResult:
    reasons: List[str] = []

    # ---- Hard gate: species ----
    if (lost.species != Species.unknown and found.species != Species.unknown
            and lost.species != found.species):
        return AttrResult(passed=False)

    # ---- Hard gate: dates ----
    days_apart = None
    if lost.date_reported and found.date_reported:
        days_apart = (found.date_reported - lost.date_reported).days
        # found must not be reported well before the pet went missing,
        # and not absurdly long after.
        if days_apart < -cfg.date_slack_days or days_apart > cfg.date_window_days:
            return AttrResult(passed=False, days_apart=days_apart)

    # ---- Hard gate: geography ----
    miles = _distance_miles(lost, found)
    geo_hard_miles = max(cfg.max_miles * 2.0, 8.0)
    if miles is not None:
        if miles > geo_hard_miles:
            return AttrResult(passed=False, miles=miles)
    elif not boroughs_adjacent(lost.borough, found.borough):
        return AttrResult(passed=False)

    # ---- Additive similarity. Species alone (0.30) stays below the stage-1
    # bar; corroborating signals are what push a pair over it, so species-only
    # pairs neither flood the candidate set nor hog the photo budget. ----
    score = 0.0
    corroborated = False

    # species
    if lost.species != Species.unknown and found.species != Species.unknown:
        score += 0.30
        reasons.append(f"same species ({lost.species.value})")

    # colors (strong identity signal -- but only when distinctive; a single
    # shared base color like "black" or "brown" is too common to count as
    # corroboration on its own)
    cl, cf = set(lost.colors), set(found.colors)
    if cl and cf:
        score += 0.30 * _jaccard(cl, cf)
        overlap = cl & cf
        if overlap:
            reasons.append("colors: " + ", ".join(sorted(overlap)))
            if (overlap & _DISTINCTIVE_COLORS) or len(overlap) >= 2:
                corroborated = True

    # breed (generic filler like "domestic shorthair" / "mix" is stripped
    # first so it can't fake a real breed match)
    bl = _tokens(lost.breed) - _GENERIC_BREED_WORDS
    bf = _tokens(found.breed) - _GENERIC_BREED_WORDS
    if bl and bf:
        j = _jaccard(bl, bf)
        score += 0.20 * j
        if j > 0:
            reasons.append("breed overlap: " + ", ".join(sorted(bl & bf)))
            corroborated = True

    # size
    if lost.size and found.size and lost.size == found.size:
        score += 0.07
        reasons.append(f"size {lost.size}")

    # sex
    if (lost.sex != Sex.unknown and found.sex != Sex.unknown
            and lost.sex == found.sex):
        score += 0.08
        reasons.append(f"sex {lost.sex.value}")

    # geography (closer is better)
    if miles is not None:
        score += 0.20 * max(0.0, 1.0 - miles / geo_hard_miles)
        reasons.append(f"{miles:.1f} mi apart")
    elif lost.borough and found.borough:
        if lost.borough == found.borough:
            score += 0.12
            reasons.append("same borough")
        else:
            score += 0.04
            reasons.append("adjacent boroughs")

    # date closeness
    if days_apart is not None:
        score += 0.08 * max(0.0, 1.0 - abs(days_apart) / cfg.date_window_days)
        reasons.append(f"{abs(days_apart)} days apart")

    # free-text similarity (names + descriptions). Character-level ratio still
    # feeds the score (smooth signal for ranking), but corroboration requires
    # actual shared content words -- not shared boilerplate phrasing.
    lt = " ".join(filter(None, [lost.name, lost.description]))
    ft = " ".join(filter(None, [found.name, found.description]))
    if lt and ft:
        ratio = SequenceMatcher(None, lt.lower()[:500], ft.lower()[:500]).ratio()
        score += 0.15 * ratio
        lt_words = _tokens(lt) - _TEXT_STOPWORDS
        ft_words = _tokens(ft) - _TEXT_STOPWORDS
        shared_words = lt_words & ft_words
        if len(shared_words) >= 2:
            reasons.append("shared description terms: " + ", ".join(sorted(shared_words)))
            corroborated = True

    return AttrResult(passed=True, score=round(min(score, 1.0), 4),
                      reasons=reasons, miles=miles, days_apart=days_apart,
                      corroborated=corroborated)
