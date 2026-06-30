"""NYC Craigslist lost & found scraper.

The search page (`/search/laf`) lists detail-page anchors whose URL encodes the
sub-area (mnh/brk/que/brx/stn = the five boroughs) and a slug. We pre-filter to
pet-related, NYC-area posts from the slug, then fetch each detail page for title,
posting date, coordinates, images and body. The "newyork" site also covers CT/NJ/
Long Island, so non-borough posts are dropped unless their coordinates fall inside
the city.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from ..geo import haversine_miles
from ..models import PetRecord, Source, Status
from ..normalize import enrich_from_text
from .base import Fetcher, Source as BaseSource

SEARCH_URL = "https://newyork.craigslist.org/search/laf"
DETAIL_RE = re.compile(
    r"https://newyork\.craigslist\.org/([a-z]{3})/laf/d/([a-z0-9-]+)/(\d+)\.html"
)
IMG_RE = re.compile(
    r"https://images\.craigslist\.org/([A-Za-z0-9_]+)_\d+x\d+[a-z]?\.jpg"
)

AREA_BOROUGH = {
    "mnh": "Manhattan", "brk": "Brooklyn", "que": "Queens",
    "brx": "Bronx", "stn": "Staten Island",
}
NYC_CENTER = (40.7549, -73.9840)
NYC_RADIUS_MILES = 35.0

PET_HINTS = [
    "cat", "kitten", "kitty", "feline", "dog", "puppy", "pup", "canine",
    "parrot", "bird", "parakeet", "cockatiel", "tabby", "calico", "terrier",
    "chihuahua", "husky", "poodle", "shepherd", "pet", "pitbull", "pit-bull",
    "yorkie", "maltese", "beagle", "dachshund", "shih-tzu", "retriever",
]


def _status_from_title(title: str) -> Optional[Status]:
    t = title.lower()
    if re.search(r"\bfound\b", t):
        return Status.found
    if re.search(r"\b(lost|missing|reward)\b", t):
        return Status.lost
    return None


def _looks_like_pet(slug: str) -> bool:
    return any(h in slug for h in PET_HINTS)


def _extract_images(html: str) -> list:
    """Craigslist embeds gallery image URLs in a script blob, not <img> tags,
    so scan the raw HTML for the image-id pattern and prefer the 600x450 size."""
    seen, out = set(), []
    for img_id in IMG_RE.findall(html):
        if img_id not in seen:
            seen.add(img_id)
            out.append(f"https://images.craigslist.org/{img_id}_600x450.jpg")
    return out


class CraigslistSource(BaseSource):
    name = "craigslist"

    def fetch(self, fetcher: Fetcher, limit: Optional[int] = None,
              existing_ids: Optional[set] = None) -> Iterable[PetRecord]:
        existing_ids = existing_ids or set()
        html = fetcher.get(SEARCH_URL, use_cache=False)
        if not html:
            return
        seen_pids = set()
        candidates = []
        for area, slug, pid in DETAIL_RE.findall(html):
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            if not _looks_like_pet(slug):
                continue
            candidates.append((area, slug, pid))

        yielded = 0
        for area, slug, pid in candidates:
            rec = self._build_record(area, slug, pid, fetcher)
            if rec is None:
                continue
            yield rec
            yielded += 1
            if limit and yielded >= limit:
                return

    def _build_record(self, area: str, slug: str, pid: str,
                      fetcher: Fetcher) -> Optional[PetRecord]:
        url = (f"https://newyork.craigslist.org/{area}/laf/d/{slug}/{pid}.html")
        html = fetcher.get(url, use_cache=True)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        title_el = soup.find(id="titletextonly")
        title = title_el.get_text(strip=True) if title_el else slug.replace("-", " ")
        status = _status_from_title(title)
        if status is None:
            return None

        # date
        date_reported = None
        time_el = soup.find("time", class_="date")
        if time_el and time_el.get("datetime"):
            try:
                date_reported = dateparser.parse(time_el["datetime"]).date()
            except (ValueError, OverflowError, TypeError):
                pass

        # geo
        lat = lon = None
        map_el = soup.find(id="map") or soup.find(attrs={"data-latitude": True})
        if map_el:
            try:
                lat = float(map_el.get("data-latitude"))
                lon = float(map_el.get("data-longitude"))
            except (TypeError, ValueError):
                lat = lon = None

        borough = AREA_BOROUGH.get(area)
        # NYC filter: keep borough posts, or out-of-borough posts whose coords
        # fall inside the city. Drop everything else (CT/NJ/LI).
        if borough is None:
            if lat is None or lon is None:
                return None
            if haversine_miles(lat, lon, *NYC_CENTER) > NYC_RADIUS_MILES:
                return None

        # neighborhood text
        neighborhood = None
        small = soup.select_one(".postingtitletext small")
        if small:
            neighborhood = small.get_text(strip=True).strip("()")

        # body
        body_el = soup.find(id="postingbody")
        body = None
        if body_el:
            body = body_el.get_text(" ", strip=True)
            body = re.sub(r"QR Code Link to This Post", "", body).strip()

        images = _extract_images(html)
        location_text = " ".join(filter(None, [neighborhood, borough]))

        pet = PetRecord.build(
            Source.craigslist,
            pid,
            status=status,
            name=None,
            description=" ".join(filter(None, [title, body]))[:1500],
            location_text=location_text or None,
            borough=borough,
            lat=lat,
            lon=lon,
            date_reported=date_reported,
            photo_urls=images,
            detail_url=url,
            raw={"title": title, "area": area, "slug": slug},
        )
        return enrich_from_text(pet)


if __name__ == "__main__":  # python -m petmatch.sources.craigslist --limit 3
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()
    f = Fetcher()
    try:
        for r in CraigslistSource().fetch(f, limit=args.limit):
            print(r.model_dump_json(indent=2, exclude={"raw"}))
            print("-" * 60)
    finally:
        f.close()
