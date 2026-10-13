"""eBay — active listings (Browse API) and sold comps (Marketplace Insights API).

Browse API works with any eBay developer keyset (client-credentials token).
Marketplace Insights (sold items) is a limited-release API: if your keyset is not approved
the source logs a warning once and the tool falls back to PriceCharting + your CSV imports.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timezone

from ..models import Listing, Sale, Target
from ..parse import parse_title
from .base import Source, SourceError

log = logging.getLogger(__name__)

API = "https://api.ebay.com"
CCG_SINGLES_CATEGORY = "183454"  # Collectible Card Games > CCG Individual Cards


def _dt(s: str | None):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Ebay(Source):
    name = "ebay"

    def __init__(self, cfg):
        super().__init__(cfg)
        self._token = None
        self._token_exp = 0.0
        self._insights_ok = True

    def enabled(self) -> bool:
        return super().enabled() and bool(self.cfg.get("client_id") and self.cfg.get("client_secret"))

    def _auth(self) -> dict:
        if not self._token or time.time() > self._token_exp - 60:
            basic = base64.b64encode(f"{self.cfg['client_id']}:{self.cfg['client_secret']}".encode()).decode()
            scopes = "https://api.ebay.com/oauth/api_scope"
            if self.cfg.get("use_marketplace_insights", True):
                scopes += " https://api.ebay.com/oauth/api_scope/buy.marketplace.insights"
            r = self.session.post(f"{API}/identity/v1/oauth2/token", timeout=30,
                                  headers={"Authorization": f"Basic {basic}",
                                           "Content-Type": "application/x-www-form-urlencoded"},
                                  data={"grant_type": "client_credentials", "scope": scopes})
            if r.status_code == 400 and "insights" in scopes:
                # Keyset not approved for Insights: retry with the base scope only.
                self.cfg["use_marketplace_insights"] = False
                self._insights_ok = False
                return self._auth()
            if r.status_code != 200:
                raise SourceError(f"eBay token request failed: {r.status_code} {r.text[:200]}")
            j = r.json()
            self._token, self._token_exp = j["access_token"], time.time() + int(j.get("expires_in", 7200))
        return {"Authorization": f"Bearer {self._token}",
                "X-EBAY-C-MARKETPLACE-ID": self.cfg.get("marketplace", "EBAY_US")}

    def _params(self, target: Target) -> dict:
        lo, hi = self.cfg.get("search_price_min", 500), self.cfg.get("search_price_max", 15000)
        cur = self.cfg.get("search_currency", "USD")
        return {
            "q": target.query(),
            "category_ids": CCG_SINGLES_CATEGORY,
            "filter": f"price:[{lo}..{hi}],priceCurrency:{cur}",
            "limit": 200,
        }

    def listings(self, target: Target) -> list[Listing]:
        p = self._params(target)
        p["filter"] += ",buyingOptions:{FIXED_PRICE|AUCTION|BEST_OFFER}"
        r = self._get(f"{API}/buy/browse/v1/item_summary/search", params=p, headers=self._auth())
        if r.status_code != 200:
            raise SourceError(f"eBay browse {r.status_code}: {r.text[:200]}")
        out = []
        for it in r.json().get("itemSummaries", []):
            res = parse_title(it.get("title", ""), hint=target.key, allowed_grades=(target.key.grade,))
            if not res.key:
                continue
            auction = "AUCTION" in it.get("buyingOptions", []) and "FIXED_PRICE" not in it.get("buyingOptions", [])
            price = it.get("currentBidPrice") if auction else it.get("price")
            if not price:
                continue
            ship = 0.0
            for so in it.get("shippingOptions", []) or []:
                c = so.get("shippingCost")
                if c:
                    ship = float(c.get("value", 0))
                    break
            out.append(Listing(
                source=self.name, key=res.key, title=it["title"], price=float(price["value"]),
                currency=price["currency"], shipping=ship, url=it.get("itemWebUrl", ""),
                seller=(it.get("seller") or {}).get("username", ""),
                seller_country=(it.get("itemLocation") or {}).get("country", ""),
                is_auction=auction, ends_at=_dt(it.get("itemEndDate")), item_id=it.get("itemId", ""),
                name=target.name,
            ))
        return out

    def sales(self, target: Target) -> list[Sale]:
        if not self._insights_ok or not self.cfg.get("use_marketplace_insights", True):
            return []
        headers = self._auth()
        if not self._insights_ok:
            return []
        r = self._get(f"{API}/buy/marketplace_insights/v1_beta/item_sales/search",
                      params=self._params(target), headers=headers)
        if r.status_code in (401, 403):
            log.warning("eBay Marketplace Insights not available for this keyset; "
                        "use PriceCharting and/or CSV imports for sold comps.")
            self._insights_ok = False
            return []
        if r.status_code != 200:
            raise SourceError(f"eBay insights {r.status_code}: {r.text[:200]}")
        out = []
        for it in r.json().get("itemSales", []):
            res = parse_title(it.get("title", ""), hint=target.key, allowed_grades=(target.key.grade,))
            if not res.key or not it.get("lastSoldPrice"):
                continue
            out.append(Sale(
                source=self.name, key=res.key, price=float(it["lastSoldPrice"]["value"]),
                currency=it["lastSoldPrice"]["currency"],
                sold_at=_dt(it.get("lastSoldDate")) or datetime.now(timezone.utc),
                title=it["title"], url=it.get("itemWebUrl", ""), item_id=it.get("itemId", ""),
            ))
        return out
