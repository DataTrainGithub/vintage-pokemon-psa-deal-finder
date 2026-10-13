"""Cardmarket (MKM API 2.0) — primary source for EU listings.

Cardmarket has no structured "graded" field for Pokémon singles; sellers put the slab in the
article comment ("PSA 10", "PSA 9 Mint", ...). We fetch every article of the matching product
and keep only those whose comment parses as the target PSA grade.

Cardmarket also exposes a price guide (TREND/AVG30 etc.), but those numbers are for raw cards,
so they are reported as context only and never used as the graded fair value.

Auth: OAuth 1.0a with a "Dedicated App" (app token + secret + access token + secret), created in
your Cardmarket account under Account > Settings > API. HMAC-SHA1 signing is implemented
below so no extra dependency is needed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from urllib.parse import quote, urlencode

from ..catalog import SETS
from ..models import Listing, Target
from ..parse import parse_title
from .base import Source, SourceError

log = logging.getLogger(__name__)

API = "https://api.cardmarket.com/ws/v2.0/output.json"
POKEMON_GAME_ID = 6
ENGLISH = 1


def _pct(s: str) -> str:
    return quote(str(s), safe="~-._")


def oauth_header(method: str, url: str, params: dict, app_token: str, app_secret: str,
                 access_token: str, access_secret: str, nonce: str = None, ts: str = None) -> str:
    """MKM-flavoured OAuth 1.0a header (realm = the request URL without query)."""
    oauth = {
        "oauth_consumer_key": app_token,
        "oauth_token": access_token,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_timestamp": ts or str(int(time.time())),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth}
    param_str = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(all_params.items()))
    base = "&".join([method.upper(), _pct(url), _pct(param_str)])
    key = f"{_pct(app_secret)}&{_pct(access_secret)}"
    sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return f'OAuth realm="{url}", ' + ", ".join(f'{k}="{_pct(v)}"' for k, v in oauth.items())


class Cardmarket(Source):
    name = "cardmarket"

    def enabled(self) -> bool:
        need = ("app_token", "app_secret", "access_token", "access_secret")
        return super().enabled() and all(self.cfg.get(k) for k in need)

    def _api(self, path: str, params: dict = None) -> dict:
        url = f"{API}/{path}"
        params = params or {}
        hdr = oauth_header("GET", url, params, self.cfg["app_token"], self.cfg["app_secret"],
                           self.cfg["access_token"], self.cfg["access_secret"])
        r = self._get(url + ("?" + urlencode(params) if params else ""), headers={"Authorization": hdr})
        if r.status_code == 204:  # MKM returns 204 for "no results"
            return {}
        if r.status_code in (401, 403):
            raise SourceError(f"Cardmarket auth failed ({r.status_code}); check your Dedicated App tokens")
        r.raise_for_status()
        return r.json()

    def _find_products(self, target: Target) -> list[dict]:
        s = SETS[target.key.set_code]
        data = self._api("products/find", {"search": target.name, "exact": "false",
                                           "idGame": POKEMON_GAME_ID, "idLanguage": ENGLISH})
        wanted = {e.lower() for e in s.cardmarket}
        out = []
        for p in data.get("product", []):
            exp = (p.get("expansionName") or p.get("expansion", {}).get("enName") or "").lower()
            num = str(p.get("number") or "").split("/")[0].lstrip("0")
            if exp not in wanted or (num and num != target.key.number):
                continue
            # Shadowless lives in its own expansion on Cardmarket; keep products consistent with the variant.
            if "shadowless" in exp and target.key.variant != "shadowless":
                continue
            if target.key.variant == "shadowless" and "shadowless" not in exp:
                continue
            out.append(p)
        return out

    def listings(self, target: Target) -> list[Listing]:
        out: list[Listing] = []
        for p in self._find_products(target):
            pid = p["idProduct"]
            web = "https://www.cardmarket.com" + (p.get("website") or "")
            start = 0
            while True:
                data = self._api(f"articles/{pid}", {"start": start, "maxResults": 1000, "idLanguage": ENGLISH})
                arts = data.get("article", [])
                for a in arts:
                    lst = self._to_listing(a, target, web)
                    if lst:
                        out.append(lst)
                if len(arts) < 1000:
                    break
                start += 1000
        return out

    def raw_price_guide(self, target: Target) -> dict:
        """Raw (ungraded) TREND/AVG30 etc. — useful context, not a graded valuation."""
        for p in self._find_products(target):
            d = self._api(f"products/{p['idProduct']}")
            return d.get("product", {}).get("priceGuide", {}) or {}
        return {}

    def _to_listing(self, a: dict, target: Target, web: str) -> Listing | None:
        comment = a.get("comments") or ""
        first = a.get("isFirstEd")
        # Build a pseudo-title: the product identity is known, the comment carries grade info.
        title = f"{target.name} {SETS[target.key.set_code].name} #{target.key.number}"
        if target.key.variant == "shadowless":
            title += " Shadowless"
        elif first or target.key.variant == "1st" and first is None:
            title += " 1st Edition"
        title += f" | {comment}"
        res = parse_title(title, hint=target.key, allowed_grades=(target.key.grade,))
        if not res.key or res.key != target.key:
            return None
        seller = a.get("seller") or {}
        return Listing(
            source=self.name, key=res.key, title=comment.strip() or title, price=float(a["price"]),
            currency="EUR", url=web, seller=seller.get("username", ""),
            seller_country=(seller.get("address") or {}).get("country", ""), item_id=str(a.get("idArticle", "")),
            name=target.name,
        )
