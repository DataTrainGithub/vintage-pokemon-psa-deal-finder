"""Import sold comps (or listings) from CSV — for 130point, PSA Auction Prices Realized,
Goldin/PWCC/Heritage results, Cardmarket order history, or anything you copy into a sheet.

Required columns: date, price, currency, title
Optional columns: url, source, set, number, variant, grade, kind (sale|listing), shipping, seller_country, name
If set/number/variant/grade are missing they are parsed from the title.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..catalog import SETS, normalise_variant
from ..models import CardKey, Listing, Sale
from ..parse import parse_title

log = logging.getLogger(__name__)


def _date(s: str) -> datetime:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _price(s: str) -> float:
    s = s.strip().replace("$", "").replace("€", "").replace("£", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) == 2 else s.replace(",", "")
    return float(s)


def load_csv(path: Path) -> tuple[list[Sale], list[Listing], dict]:
    sales, listings, rejects = [], [], {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            title = row.get("title", "")
            if row.get("set") and row.get("number") and row.get("grade"):
                set_code = row["set"]
                if set_code not in SETS:
                    rejects["unknown set code"] = rejects.get("unknown set code", 0) + 1
                    continue
                key = CardKey(set_code, row["number"].lstrip("0"),
                              normalise_variant(set_code, row.get("variant") or "unlimited"), int(row["grade"]))
            else:
                res = parse_title(title)
                if not res.key:
                    rejects[res.reason] = rejects.get(res.reason, 0) + 1
                    continue
                key = res.key
            src = row.get("source") or f"csv:{path.stem}"
            if row.get("kind", "sale") == "listing":
                listings.append(Listing(src, key, title, _price(row["price"]), row.get("currency", "USD").upper(),
                                        row.get("url", ""), shipping=_price(row["shipping"]) if row.get("shipping") else 0.0,
                                        seller_country=row.get("seller_country", ""), name=row.get("name", "")))
            else:
                sales.append(Sale(src, key, _price(row["price"]), row.get("currency", "USD").upper(),
                                  _date(row["date"]), title, row.get("url", ""),
                                  item_id=row.get("url") or f"{path.name}:{row['date']}:{row['price']}:{title}"))
    return sales, listings, rejects
