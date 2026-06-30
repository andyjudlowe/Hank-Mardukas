"""Petco Love Lost scraper.

Petco Love Lost is a Next.js app: each page embeds a __NEXT_DATA__ JSON blob.
The NY listing (`/lost/lost-and-found-pets/new-york/<page>/`) carries lightweight
pet cards; shelter-hosted pets also have a rich detail page
(`/lost/pet/<type>/<ownerType>/<petId>/`) with species, ZIP, coordinates, sex,
breed and shelter contact. The "new-york" feed is NY *state*, so we drop records
that resolve to a non-NYC ZIP or sit far from the city.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Iterable, Optional

from dateutil import parser as dateparser

from ..config import CONFIG
from ..geo import haversine_miles, zip_to_borough
from ..models import PetRecord, Sex, Source, Species, Status
from ..normalize import enrich_from_text
from .base import Fetcher, Source as BaseSource

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
PET_ID_RE = re.compile(r"/photos/pet/(\d+)/")
# Rough NYC center (Midtown) for a coarse distance sanity check.
NYC_CENTER = (40.7549, -73.9840)
NYC_RADIUS_MILES = 35.0

LIST_URL = "https://petcolove.org/lost/lost-and-found-pets/new-york/{page}/"


def _parse_next_data(html: str) -> Optional[dict]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _clean_images(images) -> list:
    out = []
    for u in images or []:
        if not u or "placeholder" in u:
            continue
        out.append(u.split("?")[0])  # drop width/format query params
    # de-dup, preserve order
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _species_from_str(s: Optional[str]) -> Species:
    if not s:
        return Species.unknown
    s = s.lower()
    if "dog" in s:
        return Species.dog
    if "cat" in s:
        return Species.cat
    if "bird" in s:
        return Species.bird
    return Species.other


def _sex_from_str(s: Optional[str]) -> Sex:
    if not s:
        return Sex.unknown
    s = s.lower()
    if s.startswith("m"):
        return Sex.male
    if s.startswith("f"):
        return Sex.female
    return Sex.unknown


def _is_non_nyc(zipcode: Optional[str], lat: Optional[float],
                lon: Optional[float]) -> bool:
    """True only when we have positive evidence the pet is outside NYC."""
    if zipcode and zipcode[:5].isdigit() and zip_to_borough(zipcode) is None:
        return True
    if lat is not None and lon is not None:
        if haversine_miles(lat, lon, *NYC_CENTER) > NYC_RADIUS_MILES:
            return True
    return False


class PetcoSource(BaseSource):
    name = "petco"

    def fetch(self, fetcher: Fetcher, limit: Optional[int] = None,
              existing_ids: Optional[set] = None) -> Iterable[PetRecord]:
        existing_ids = existing_ids or set()
        yielded = 0
        max_pages = CONFIG.petco_max_pages
        for page in range(1, max_pages + 1):
            url = LIST_URL.format(page=page)
            # Listing pages change constantly -> don't read them from cache.
            html = fetcher.get(url, use_cache=False)
            if not html:
                break
            data = _parse_next_data(html)
            if not data:
                break
            pp = data.get("props", {}).get("pageProps", {})
            pets = pp.get("pets", [])
            if not pets:
                break
            for raw in pets:
                rec = self._build_record(raw, fetcher, existing_ids)
                if rec is None:
                    continue
                yield rec
                yielded += 1
                if limit and yielded >= limit:
                    return
            pagination = pp.get("pagination", {})
            if not pagination.get("hasNextPage"):
                break

    def _build_record(self, raw: dict, fetcher: Fetcher,
                      existing_ids: set) -> Optional[PetRecord]:
        images = _clean_images(raw.get("images"))
        pet_id = None
        for u in images:
            m = PET_ID_RE.search(u)
            if m:
                pet_id = m.group(1)
                break
        ptype = (raw.get("type") or "").lower()
        if ptype not in ("lost", "found"):
            return None
        status = Status(ptype)
        external_url = raw.get("url") or None
        source_id = pet_id or (external_url or json.dumps(raw, sort_keys=True))
        from ..models import make_pet_id
        rec_id = make_pet_id(Source.petco, source_id)

        list_date = None
        if raw.get("date"):
            try:
                list_date = dateparser.parse(raw["date"]).date()
            except (ValueError, OverflowError, TypeError):
                list_date = None

        # The list `ownerType` ("awo"/"shelter"/"municipal"/"user") does not map
        # 1:1 to the detail-URL segment, which is "s" (org) or "u" (user). Try the
        # likely one first, then the other.
        ot_raw = (raw.get("ownerType") or "").lower()
        owner_paths = (["u", "s"] if ot_raw in ("user", "individual", "u")
                       else ["s", "u"])
        reporter = raw.get("source") or raw.get("reporterName")

        # Enrich from the detail page for shelter/petco-hosted pets only. Pets
        # aggregated from Neighbors/Nextdoor carry an external `url` and have no
        # Petco detail page (those 404), so we keep their list-level data as-is.
        detail = None
        detail_url = None
        # Skip the (cacheable) detail fetch if we already stored this pet.
        if pet_id and external_url is None and rec_id not in existing_ids:
            for ot in owner_paths:
                candidate = (f"https://petcolove.org/lost/pet/{ptype}/"
                             f"{ot}/{pet_id}/")
                dhtml = fetcher.get(candidate, use_cache=True)
                if not dhtml:
                    continue
                dd = _parse_next_data(dhtml)
                pp = (dd or {}).get("props", {}).get("pageProps", {})
                if pp.get("petDetails"):
                    detail = pp
                    detail_url = candidate
                    break

        kwargs = dict(
            status=status,
            name=raw.get("petName") or None,
            date_reported=list_date,
            photo_urls=images,
            detail_url=external_url or detail_url,
        )

        if detail:
            pd = detail.get("petDetails", {}) or {}
            attrs = pd.get("attributes", {}) or {}
            coords = pd.get("coordinates", {}) or {}
            shelter = detail.get("shelterDetails", {}) or {}
            zipcode = pd.get("zip")
            lat = coords.get("latitude")
            lon = coords.get("longitude")
            if _is_non_nyc(zipcode, lat, lon):
                return None
            kwargs.update(
                species=_species_from_str(pd.get("species")),
                sex=_sex_from_str(attrs.get("sex")),
                breed=attrs.get("breed") or None,
                zip=zipcode,
                lat=lat,
                lon=lon,
                location_text=attrs.get("foundLocation") or pd.get("city"),
                description=pd.get("notes") or None,
            )
            if pd.get("images"):
                more = _clean_images(pd["images"])
                kwargs["photo_urls"] = more or images
            if shelter:
                contact_bits = [shelter.get("name"), shelter.get("phone"),
                                shelter.get("email")]
                kwargs["contact"] = " | ".join(b for b in contact_bits if b) or None
            if pd.get("date"):
                try:
                    kwargs["date_reported"] = dateparser.parse(pd["date"]).date()
                except (ValueError, OverflowError, TypeError):
                    pass

        pet = PetRecord.build(Source.petco, source_id, raw=raw, **kwargs)
        if reporter:
            pet.raw["reporter"] = reporter
        return enrich_from_text(pet)


if __name__ == "__main__":  # smoke test: python -m petmatch.sources.petco --limit 3
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()
    f = Fetcher()
    try:
        for r in PetcoSource().fetch(f, limit=args.limit):
            print(r.model_dump_json(indent=2, exclude={"raw"}))
            print("-" * 60)
    finally:
        f.close()
