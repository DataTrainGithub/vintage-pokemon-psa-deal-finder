from __future__ import annotations

import logging
import time

import requests

from ..models import Listing, Sale, Target

log = logging.getLogger(__name__)


class SourceError(Exception):
    pass


class Source:
    """A data portal. Override whichever of the two fetchers the portal supports."""

    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "vintage-deal-finder/1.0"
        self.min_interval = float(self.cfg.get("min_request_interval", 1.0))
        self._last = 0.0

    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", False))

    def listings(self, target: Target) -> list[Listing]:
        return []

    def sales(self, target: Target) -> list[Sale]:
        return []

    def _get(self, url: str, **kw) -> requests.Response:
        """Rate-limited GET with simple retry on 429/5xx."""
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self.session.get(url, timeout=30, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** (attempt + 1))
                continue
            return r
        return r
