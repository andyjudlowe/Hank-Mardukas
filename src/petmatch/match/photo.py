"""Stage 2: Claude vision confirmation that two photos show the same animal.

Only the highest-ranked stage-1 survivors reach this stage. Every comparison is
cached (keyed by the pair of photo URLs) so re-runs never re-pay for a pair.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from typing import List, Optional, Tuple

import httpx

from ..config import Config
from ..storage import photo_cache_get, photo_cache_put

PROMPT = (
    "You are comparing two photos from lost-and-found pet listings to judge "
    "whether they show the SAME individual animal.\n"
    "Image 1 is from a LOST-pet report. Image 2 is from a FOUND-pet report.\n"
    "Focus on identity-distinguishing features: species and breed, coat color and "
    "pattern/markings, ear shape, face, size and build. Ignore background, lighting, "
    "pose, and photo quality. Different individuals of the same breed are NOT a match.\n"
    'Respond ONLY with JSON: {"same_animal_likelihood": <0.0-1.0>, '
    '"reasoning": "<one concise sentence>"}'
)

_JSON_RE = re.compile(r"\{.*\}", re.S)


def cache_key(url_a: str, url_b: str) -> str:
    raw = "|".join(sorted([url_a, url_b]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _media_type(url: str, content_type: Optional[str]) -> str:
    if content_type and content_type.startswith("image/"):
        ct = content_type.split(";")[0].strip()
        if ct in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            return ct
    u = url.lower()
    if u.endswith(".png"):
        return "image/png"
    if u.endswith(".webp"):
        return "image/webp"
    if u.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def _download_image(client: httpx.Client, url: str) -> Optional[Tuple[str, str]]:
    try:
        resp = client.get(url, timeout=30.0)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or not resp.content:
        return None
    media = _media_type(url, resp.headers.get("content-type"))
    return media, base64.standard_b64encode(resp.content).decode("ascii")


def compare(
    lost_photos: List[str],
    found_photos: List[str],
    conn: sqlite3.Connection,
    cfg: Config,
    client: Optional[object] = None,
    http: Optional[httpx.Client] = None,
) -> Optional[Tuple[float, str]]:
    """Return (likelihood, reasoning) or None if a comparison wasn't possible."""
    if cfg.no_photo or not cfg.anthropic_api_key:
        return None
    if not lost_photos or not found_photos:
        return None

    url_a, url_b = lost_photos[0], found_photos[0]
    key = cache_key(url_a, url_b)
    cached = photo_cache_get(conn, key)
    if cached is not None:
        return float(cached[0]), cached[1]

    own_http = http is None
    http = http or httpx.Client(follow_redirects=True)
    try:
        img_a = _download_image(http, url_a)
        img_b = _download_image(http, url_b)
    finally:
        if own_http:
            http.close()
    if not img_a or not img_b:
        return None

    if client is None:
        from anthropic import Anthropic
        client = Anthropic(api_key=cfg.anthropic_api_key)

    try:
        resp = client.messages.create(
            model=cfg.vision_model,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Image 1 (LOST pet):"},
                    {"type": "image", "source": {
                        "type": "base64", "media_type": img_a[0], "data": img_a[1]}},
                    {"type": "text", "text": "Image 2 (FOUND pet):"},
                    {"type": "image", "source": {
                        "type": "base64", "media_type": img_b[0], "data": img_b[1]}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
    except Exception as e:  # network / API errors shouldn't crash the run
        print(f"  [vision error] {e}")
        return None

    text = "".join(getattr(b, "text", "") for b in resp.content)
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        score = float(data.get("same_animal_likelihood"))
        reasoning = str(data.get("reasoning", ""))[:300]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    score = max(0.0, min(1.0, score))
    photo_cache_put(conn, key, score, reasoning)
    return score, reasoning
