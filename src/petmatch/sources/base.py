"""Source interface plus a polite, on-disk-cached HTTP fetcher."""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, List, Optional

import httpx

from ..config import CACHE_DIR, CONFIG
from ..models import PetRecord


class Fetcher:
    """Rate-limited GET with a simple on-disk text cache.

    Caching keeps re-runs light and friendly to the source sites. Pass
    use_cache=False for endpoints whose contents change every run.
    """

    def __init__(self, cache_dir: Path = CACHE_DIR, delay_s: Optional[float] = None):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay_s = CONFIG.request_delay_s if delay_s is None else delay_s
        self._last_request = 0.0
        self.client = httpx.Client(
            headers={"User-Agent": CONFIG.user_agent,
                     "Accept-Language": "en-US,en;q=0.9"},
            timeout=30.0,
            follow_redirects=True,
        )

    def _cache_path(self, url: str) -> Path:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.html"

    def get(self, url: str, use_cache: bool = True) -> Optional[str]:
        cache_path = self._cache_path(url)
        if use_cache and cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="ignore")
        # rate limit
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay_s:
            time.sleep(self.delay_s - elapsed)
        try:
            resp = self.client.get(url)
            self._last_request = time.monotonic()
        except httpx.HTTPError as e:
            print(f"  [fetch error] {url}: {e}")
            return None
        if resp.status_code != 200:
            print(f"  [http {resp.status_code}] {url}")
            return None
        text = resp.text
        try:
            cache_path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        return text

    def close(self) -> None:
        self.client.close()


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self, fetcher: Fetcher, limit: Optional[int] = None,
              existing_ids: Optional[set] = None) -> Iterable[PetRecord]:
        """Yield normalized PetRecords. `limit` caps records for smoke tests.

        `existing_ids` lets a source skip detail-page fetches it already has.
        """
        raise NotImplementedError
