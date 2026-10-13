"""PriceCharting — graded guide prices built from eBay sold data (paid API token required).

For trading cards PriceCharting reuses its video-game price fields:
  loose-price = ungraded, new-price = grade 8, graded-price = grade 9,
  box-only-price = grade 9.5, manual-only-price = PSA 10.
Prices are in US cents. One guide price is stored as a single "guide" comp, which valuation
weights lower than real sales.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ..catalog import SETS
from ..models import Sale, Target
from .base import Source, SourceError

log = logging.getLogger(__name__)

API = "https://www.pricecharting.com/api"
GRADE_FIELD = {9: "graded-price", 10: "manual-only-price", 8: "new-price"}


class PriceCharting(Source):
    name = "pricecharting"

    def enabled(self) -> bool:
        return super().enabled() and bool(self.cfg.get("token"))

    def _match(self, p: dict, target: Target) -> bool:
        s = SETS[target.key.set_code]
        console = (p.get("console-name") or "").lower()
        pname = (p.get("product-name") or "").lower()
        if not console.startswith(s.pricecharting.lower()):
            return False
        # "Pokemon Base Set" must not match "Pokemon Base Set 2"
        rest = console[len(s.pricecharting):].strip()
        if rest and rest not in ("shadowless", "1st edition"):
            return False
        if not re.search(rf"#0*{re.escape(target.key.number)}\b", pname):
            return False
        both = f"{console} {pname}"
        is_1st = "1st edition" in both
        is_shadowless = "shadowless" in both
        v = target.key.variant
        return (v == "1st" and is_1st) or (v == "shadowless" and is_shadowless and not is_1st) or \
               (v == "unlimited" and not is_1st and not is_shadowless)

    def sales(self, target: Target) -> list[Sale]:
        field = GRADE_FIELD.get(target.key.grade)
        if not field:
            return []
        q = f"{target.name} {SETS[target.key.set_code].name} {target.key.number}"
        r = self._get(f"{API}/products", params={"t": self.cfg["token"], "q": q})
        if r.status_code != 200:
            raise SourceError(f"PriceCharting {r.status_code}: {r.text[:200]}")
        for p in r.json().get("products", []):
            if self._match(p, target) and p.get(field):
                return [Sale(
                    source=self.name, key=target.key, price=p[field] / 100.0, currency="USD",
                    sold_at=datetime.now(timezone.utc), title=f"{p['product-name']} ({p['console-name']})",
                    url=f"https://www.pricecharting.com/game/{p.get('id')}", item_id=f"pc-{p.get('id')}",
                    is_guide=True,
                )]
        return []
