"""Orchestration: watchlist -> sources -> history -> valuation -> deals."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .catalog import SETS, normalise_variant
from .fx import FX
from .models import CardKey, Deal, Listing, Target, Valuation
from .scoring import is_deal, score
from .sources.base import SourceError
from .sources.cardmarket import Cardmarket
from .sources.csv_import import load_csv
from .sources.demo import Demo
from .sources.ebay import Ebay
from .sources.pricecharting import PriceCharting
from .store import Store
from .valuation import fair_value

log = logging.getLogger(__name__)


@dataclass
class MarketRow:
    target: Target
    valuation: Valuation
    listings: int
    cheapest: Deal | None
    raw_trend: float | None = None


@dataclass
class ScanResult:
    deals: list[Deal]
    market: list[MarketRow]
    stats: dict = field(default_factory=dict)
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def build_targets(watchlist: list[dict], default_grades=(9, 10)) -> list[Target]:
    targets, seen = [], set()
    for w in watchlist:
        set_code = w["set"]
        if set_code not in SETS:
            raise ValueError(f"Unknown set code '{set_code}' in watchlist (known: {', '.join(SETS)})")
        for variant in w.get("variants", ["unlimited"]):
            v = normalise_variant(set_code, variant)
            for g in w.get("grades", default_grades):
                key = CardKey(set_code, str(w["number"]).lstrip("0"), v, int(g))
                if key not in seen:
                    seen.add(key)
                    targets.append(Target(key, w["name"]))
    return targets


def make_sources(cfg: dict, demo: bool) -> list:
    if demo:
        return [Demo({})]
    srcs = [Cardmarket(cfg.get("cardmarket", {})), Ebay(cfg.get("ebay", {})),
            PriceCharting(cfg.get("pricecharting", {}))]
    active = [s for s in srcs if s.enabled()]
    for s in srcs:
        if s not in active:
            log.info("source %s disabled or missing credentials", s.name)
    return active


def run(cfg: dict, watchlist: list[dict], demo: bool = False, store: Store = None, now: datetime = None) -> ScanResult:
    now = now or datetime.now(timezone.utc)
    deal_cfg = cfg.get("deals", {})
    fx_cfg = cfg.get("fx", {})
    fx = FX(fx_cfg.get("base", "EUR"), fx_cfg.get("fallback_rates", {}), live=fx_cfg.get("live", True) and not demo)
    store = store or Store(cfg.get("database", "data/history.sqlite"))
    targets = build_targets(watchlist, tuple(cfg.get("grades", (9, 10))))
    sources = make_sources(cfg, demo)
    if demo:
        sources[0].now = now
    elif not sources:
        log.warning("No live sources configured (set API keys in config.yaml); only CSV imports will be used")
    stats = defaultdict(int)
    listings: list[Listing] = []
    raw_trend: dict[CardKey, float] = {}

    # 1. CSV imports (sold history from 130point / PSA APR / auction houses, or manual listings)
    imp = Path(cfg.get("imports_dir", "imports"))
    if imp.is_dir():
        for p in sorted(imp.glob("*.csv")):
            sales, lst, rej = load_csv(p)
            stats["csv_sales_new"] += store.add_sales(sales)
            listings += lst
            for r, n in rej.items():
                stats[f"rejected: {r}"] += n

    # 2. Live sources, per target
    dead = set()
    for t in targets:
        for src in sources:
            if src.name in dead:
                continue
            try:
                s = src.sales(t)
                stats[f"{src.name}_sales_new"] += store.add_sales(s)
                found = src.listings(t)
                stats[f"{src.name}_listings"] += len(found)
                listings += found
                if isinstance(src, Cardmarket) and src.cfg.get("fetch_raw_trend"):
                    pg = src.raw_price_guide(t)
                    if pg.get("TREND"):
                        raw_trend[t.key] = float(pg["TREND"])
            except SourceError as e:
                log.error("%s: %s — disabling for this run", src.name, e)
                dead.add(src.name)
            except Exception as e:  # network hiccup on one target shouldn't kill the scan
                log.warning("%s failed for %s: %s", src.name, t.key.label(t.name), e)
                stats[f"{src.name}_errors"] += 1
    for src in sources:
        for r, n in getattr(src, "rejected", {}).items():
            stats[f"rejected: {r}"] += n

    # 3. Value + score
    vcfg = cfg.get("valuation", {})
    vals: dict[CardKey, Valuation] = {}

    def valuation(key):
        if key not in vals:
            vals[key] = fair_value(store.sales_for(key), fx, now, vcfg.get("lookback_days", 180),
                                   vcfg.get("half_life_days", 45), vcfg.get("guide_weight", 0.5))
        return vals[key]

    by_key = defaultdict(list)
    seen_ids = set()
    for l in listings:
        uid = (l.source, l.item_id or l.url)
        if uid in seen_ids:
            continue
        seen_ids.add(uid)
        d = score(l, valuation(l.key), fx, deal_cfg)
        if d:
            by_key[l.key].append(d)
        else:
            stats["listings_without_fmv"] += 1

    deals = sorted((d for ds in by_key.values() for d in ds if is_deal(d, deal_cfg)), key=lambda d: -d.score)

    names = {t.key: t.name for t in targets}
    market = []
    for key in list(dict.fromkeys([t.key for t in targets] + list(by_key))):
        ds = by_key.get(key, [])
        cheapest = min(ds, key=lambda d: d.landed_cost) if ds else None
        market.append(MarketRow(Target(key, names.get(key) or (ds[0].listing.name if ds else "")),
                                valuation(key), len(ds), cheapest, raw_trend.get(key)))
    stats["targets"] = len(targets)
    stats["listings_valued"] = sum(len(v) for v in by_key.values())
    return ScanResult(deals, market, dict(stats), now)
