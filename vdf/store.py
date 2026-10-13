"""SQLite history. Sold comps accumulate across runs (sold-data APIs are rate-limited or gated,
so building your own history is what makes valuations solid over time). Also remembers which
deals were already alerted."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .models import CardKey, Sale

SCHEMA = """
CREATE TABLE IF NOT EXISTS sales (
  source TEXT, item_id TEXT, key TEXT, set_code TEXT, number TEXT, variant TEXT, grade INT, grader TEXT,
  language TEXT, price REAL, currency TEXT, sold_at TEXT, title TEXT, url TEXT, is_guide INT,
  PRIMARY KEY (source, item_id, sold_at)
);
CREATE INDEX IF NOT EXISTS sales_key ON sales(key);
CREATE TABLE IF NOT EXISTS alerted (source TEXT, item_id TEXT, price REAL, at TEXT, PRIMARY KEY (source, item_id, price));
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def add_sales(self, sales: list[Sale]) -> int:
        before = self.db.total_changes
        for s in sales:
            k = s.key
            item = s.item_id or s.url or f"{s.title}:{s.price}"
            # Guide prices are refreshed every run: keep only the latest per key/source.
            if s.is_guide:
                self.db.execute("DELETE FROM sales WHERE source=? AND key=? AND is_guide=1", (s.source, k.id))
            self.db.execute(
                "INSERT OR IGNORE INTO sales VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s.source, item, k.id, k.set_code, k.number, k.variant, k.grade, k.grader, k.language,
                 s.price, s.currency, s.sold_at.isoformat(), s.title, s.url, int(s.is_guide)))
        self.db.commit()
        return self.db.total_changes - before

    def sales_for(self, key: CardKey) -> list[Sale]:
        rows = self.db.execute(
            "SELECT source, item_id, price, currency, sold_at, title, url, is_guide FROM sales WHERE key=?", (key.id,))
        return [Sale(r[0], key, r[2], r[3], datetime.fromisoformat(r[4]), r[5], r[6], r[1], bool(r[7])) for r in rows]

    def keys(self) -> list[CardKey]:
        rows = self.db.execute("SELECT DISTINCT set_code, number, variant, grade, grader, language FROM sales")
        return [CardKey(*r) for r in rows]

    def was_alerted(self, source: str, item_id: str, price: float) -> bool:
        return self.db.execute("SELECT 1 FROM alerted WHERE source=? AND item_id=? AND price=?",
                               (source, item_id, price)).fetchone() is not None

    def mark_alerted(self, source: str, item_id: str, price: float):
        self.db.execute("INSERT OR IGNORE INTO alerted VALUES (?,?,?,datetime('now'))", (source, item_id, price))
        self.db.commit()
