"""Synthetic data so the full pipeline can be exercised without API keys.

Prices here are invented — they illustrate the mechanics only and are NOT market data.
Titles go through the same parser as real listings, including junk that must be rejected.
"""
from __future__ import annotations

import random
import zlib
from datetime import datetime, timedelta, timezone

from ..catalog import SETS
from ..models import Listing, Sale, Target
from ..parse import parse_title
from .base import Source

JUNK = [
    "{name} {set} {num} PSA {grade} Celebrations Classic Collection",
    "{name} {set} PSA {grade} (OC) {num}",
    "{name} {set} {num} PSA {grade} READY raw mint",
    "{name} {set} {num} BGS 9.5",
    "{name} {set} {num} PSA {grade} empty slab label only",
]


class Demo(Source):
    name = "demo"

    def __init__(self, cfg, now: datetime = None):
        super().__init__(cfg)
        self.now = now or datetime.now(timezone.utc)
        self.rejected: dict[str, int] = {}

    def enabled(self) -> bool:
        return True

    def _rng(self, target: Target, salt: str) -> random.Random:
        return random.Random(zlib.crc32(f"{target.key.id}:{salt}".encode()))

    def _base_price(self, target: Target) -> float:
        return round(self._rng(target, "base").uniform(900, 9500), -1)

    def _title(self, target: Target, rng: random.Random) -> str:
        s = SETS[target.key.set_code]
        var = {"1st": rng.choice(["1st Edition", "1st Ed", "First Edition"]), "shadowless": "Shadowless",
               "unlimited": rng.choice(["Unlimited", ""])}[target.key.variant]
        num = rng.choice([f"#{target.key.number}", f"{target.key.number}/{s.total}"])
        grade = rng.choice([f"PSA {target.key.grade}", f"PSA {'GEM MINT' if target.key.grade == 10 else 'MINT'} {target.key.grade}"])
        return f"{rng.choice(['1999', '2000', ''])} Pokemon {s.name} {target.name} {var} {num} Holo {grade}".replace("  ", " ").strip()

    def sales(self, target: Target) -> list[Sale]:
        rng, base = self._rng(target, "sales"), self._base_price(target)
        out = []
        for i in range(rng.randint(2, 14)):
            age = rng.uniform(0, 170)
            drift = 1 + 0.0008 * (90 - age)  # mild uptrend
            price = base * drift * rng.gauss(1, 0.08)
            if i == 0 and rng.random() < 0.4:
                price *= rng.choice([0.35, 2.4])  # outlier (shill bid, mislabelled lot...)
            usd = rng.random() < 0.7
            out.append(Sale("demo-ebay-sold" if usd else "demo-cardmarket-sold", target.key,
                            round(price / (0.86 if usd else 1), 2), "USD" if usd else "EUR",
                            self.now - timedelta(days=age), self._title(target, rng), item_id=f"s{i}"))
        return out

    def listings(self, target: Target) -> list[Listing]:
        rng, base = self._rng(target, "listings"), self._base_price(target)
        raw = []
        for i in range(rng.randint(1, 4)):
            mult = rng.uniform(0.97, 1.35)
            if i == 0 and rng.random() < 0.22:
                mult = rng.uniform(0.62, 0.80)  # planted bargain
            cm = rng.random() < 0.55
            raw.append(("cardmarket" if cm else "ebay", self._title(target, rng), base * mult, cm, i))
        if rng.random() < 0.5:
            t = rng.choice(JUNK).format(name=target.name, set=SETS[target.key.set_code].name,
                                         num=target.key.number, grade=target.key.grade)
            raw.append(("ebay", t, base * 0.3, False, 99))
        out = []
        for src, title, eur, cm, i in raw:
            res = parse_title(title, hint=target.key, allowed_grades=(target.key.grade,))
            if not res.key:
                self.rejected[res.reason] = self.rejected.get(res.reason, 0) + 1
                continue
            country = rng.choice(["DE", "FR", "NL", "BE", "IT", "ES"]) if cm else rng.choice(["US", "US", "GB", "JP", "DE"])
            price, cur = (round(eur, 2), "EUR") if cm else (round(eur / 0.86, 2), "USD")
            out.append(Listing(f"demo-{src}", res.key, title, price, cur,
                               f"https://example.invalid/{src}/{target.key.id}/{i}",
                               shipping=0 if cm else 35.0, seller=f"seller{rng.randint(1, 999)}",
                               seller_country=country, is_auction=(not cm and rng.random() < 0.2),
                               item_id=f"{target.key.id}:{i}", name=target.name))
        return out
