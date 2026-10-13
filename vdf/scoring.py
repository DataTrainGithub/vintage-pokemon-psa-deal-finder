"""Landed cost + deal scoring.

Landed cost = price + shipping (+ import VAT and handling for listings shipped from outside the
EU when you live in the EU). Collectible trading cards carry 0% EU customs duty but import VAT is
charged on the full value (incl. shipping). The UK is outside the EU since 2021.
"""
from __future__ import annotations

from .fx import FX
from .models import Deal, Listing, Valuation

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
      "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.8, "low": 0.5, "none": 0.0}


def landed_cost(listing: Listing, fx: FX, cfg: dict) -> tuple[float, list[str]]:
    notes = []
    base = fx.to_base(listing.price + listing.shipping, listing.currency)
    fee = float(cfg.get("buyer_fee_pct", {}).get(listing.source.split(":")[0], 0.0))
    if fee:
        base *= 1 + fee
    home = cfg.get("home_country", "").upper()
    origin = (listing.seller_country or "").upper()
    if home in EU and origin and origin not in EU:
        vat = float(cfg.get("import_vat_rate", 0.21))
        base = base * (1 + vat) + float(cfg.get("import_handling_fee", 0.0))
        notes.append(f"import VAT {vat:.0%} from {origin}")
    elif home in EU and not origin:
        notes.append("seller country unknown; import costs not included")
    return base, notes


def score(listing: Listing, val: Valuation, fx: FX, cfg: dict) -> Deal | None:
    if val.fmv is None:
        return None
    cost, notes = landed_cost(listing, fx, cfg)
    discount = 1 - cost / val.fmv
    savings = val.fmv - cost
    if listing.is_auction:
        notes.append("auction: current bid, final price will be higher")
    if val.confidence == "low":
        notes.append("thin comps: verify FMV manually")
    s = discount * CONFIDENCE_FACTOR[val.confidence] * (0.6 if listing.is_auction else 1.0)
    return Deal(listing, val, cost, discount, savings, s, notes)


def is_deal(d: Deal, cfg: dict) -> bool:
    lo, hi = cfg.get("price_min", 1000), cfg.get("price_max", 10000)
    if not (lo <= d.landed_cost <= hi):
        return False
    if d.discount < cfg.get("min_discount", 0.2):
        return False
    if d.discount > cfg.get("max_discount", 0.7):
        return False  # too good to be true: almost always a mis-parse, fake or scam
    if CONFIDENCE_FACTOR[d.valuation.confidence] < CONFIDENCE_FACTOR[cfg.get("min_confidence", "low")]:
        return False
    if d.listing.is_auction and not cfg.get("include_auctions", True):
        return False
    return True
