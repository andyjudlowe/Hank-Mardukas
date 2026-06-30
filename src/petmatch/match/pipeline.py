"""Orchestrate the two-stage cascade and persist tiered matches."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

import httpx

from ..config import CONFIG, Config
from ..models import Match, MatchTier, PetRecord, Status
from ..storage import get_pets, upsert_match
from .filter import AttrResult, stage1
from .photo import compare

# Confidence blend when a photo comparison succeeded (photo dominates).
PHOTO_WEIGHT = 0.65
ATTR_WEIGHT = 0.35


@dataclass
class MatchStats:
    lost: int = 0
    found: int = 0
    stage1_survivors: int = 0
    photo_calls: int = 0
    possible: int = 0
    high: int = 0


def _tier(confidence: float, cfg: Config) -> MatchTier:
    if confidence >= cfg.email_threshold:
        return MatchTier.high
    if confidence >= cfg.dash_threshold:
        return MatchTier.possible
    return MatchTier.rejected


def _confidence(attr: float, photo: Optional[float], cfg: Config) -> float:
    if photo is None:
        # No photo confirmation possible -> cap how confident we allow attributes.
        return round(min(attr, cfg.no_photo_confidence_cap), 4)
    return round(ATTR_WEIGHT * attr + PHOTO_WEIGHT * photo, 4)


def run_matching(conn: sqlite3.Connection, cfg: Config = CONFIG,
                 do_photo: bool = True, verbose: bool = True) -> MatchStats:
    lost = get_pets(conn, Status.lost)
    found = get_pets(conn, Status.found)
    stats = MatchStats(lost=len(lost), found=len(found))

    # ---- Stage 1: attribute candidates ----
    candidates: List[tuple] = []  # (attr_score, lost, found, AttrResult)
    for lp in lost:
        for fp in found:
            res: AttrResult = stage1(lp, fp, cfg)
            if res.passed and res.score >= cfg.attr_threshold:
                candidates.append((res.score, lp, fp, res))
    candidates.sort(key=lambda c: c[0], reverse=True)
    stats.stage1_survivors = len(candidates)
    if verbose:
        print(f"  stage1: {len(candidates)} candidates from "
              f"{len(lost)}x{len(found)} pairs")

    # ---- Stage 2: photo confirmation on top survivors with photos both sides ----
    http = httpx.Client(follow_redirects=True) if do_photo else None
    anthropic_client = None
    if do_photo and not cfg.no_photo and cfg.anthropic_api_key:
        from anthropic import Anthropic
        anthropic_client = Anthropic(api_key=cfg.anthropic_api_key)

    try:
        for attr_score, lp, fp, res in candidates:
            photo_score = None
            photo_reasoning = None
            can_photo = (do_photo and lp.photo_urls and fp.photo_urls
                         and stats.photo_calls < cfg.max_vision_calls)
            if can_photo:
                out = compare(lp.photo_urls, fp.photo_urls, conn, cfg,
                              client=anthropic_client, http=http)
                if out is not None:
                    photo_score, photo_reasoning = out
                    stats.photo_calls += 1
                    conn.commit()  # persist photo cache as we go

            # Without a photo, "same species + same area" is not actionable on
            # its own -- require a distinguishing attribute overlap to surface it.
            if photo_score is None and not res.corroborated:
                continue

            confidence = _confidence(attr_score, photo_score, cfg)
            tier = _tier(confidence, cfg)
            if tier == MatchTier.rejected:
                continue

            reasons = list(res.reasons)
            if photo_reasoning:
                reasons.append(f"photo: {photo_reasoning}")

            m = Match(
                lost_id=lp.id, found_id=fp.id, attr_score=attr_score,
                photo_score=photo_score, confidence=confidence, tier=tier,
                reasons=reasons, photo_reasoning=photo_reasoning,
            )
            upsert_match(conn, m)
            if tier == MatchTier.high:
                stats.high += 1
            else:
                stats.possible += 1
        conn.commit()
    finally:
        if http is not None:
            http.close()

    if verbose:
        print(f"  matches: {stats.high} high, {stats.possible} possible "
              f"({stats.photo_calls} photo comparisons)")
    return stats
