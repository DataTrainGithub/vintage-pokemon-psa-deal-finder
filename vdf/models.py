"""Core data types shared by sources, valuation and scoring."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .catalog import SETS


@dataclass(frozen=True)
class CardKey:
    """Identity of a graded card. Two listings are comparable only if keys are equal."""

    set_code: str
    number: str
    variant: str  # "1st" | "shadowless" | "unlimited"
    grade: int
    grader: str = "PSA"
    language: str = "EN"

    def label(self, name: str = "") -> str:
        s = SETS.get(self.set_code)
        set_name = s.name if s else self.set_code
        var = {"1st": "1st Ed", "shadowless": "Shadowless", "unlimited": "Unlimited"}.get(self.variant, self.variant)
        nm = f"{name} " if name else ""
        lang = "" if self.language == "EN" else f" [{self.language}]"
        return f"{nm}#{self.number} {set_name} {var} {self.grader} {self.grade}{lang}"

    @property
    def id(self) -> str:
        return f"{self.set_code}|{self.number}|{self.variant}|{self.grader}{self.grade}|{self.language}"


@dataclass
class Target:
    """A card we actively hunt for (one variant + one grade)."""

    key: CardKey
    name: str

    def query(self, with_grade: bool = True) -> str:
        s = SETS[self.key.set_code]
        parts = [self.name, s.search_name]
        if self.key.variant == "1st":
            parts.append("1st Edition")
        elif self.key.variant == "shadowless":
            parts.append("Shadowless")
        parts.append(f"#{self.key.number}" if not self.key.number.isdigit() else self.key.number)
        if with_grade:
            parts.append(f"{self.key.grader} {self.key.grade}")
        return " ".join(parts)


@dataclass
class Listing:
    """Something currently for sale."""

    source: str
    key: CardKey
    title: str
    price: float
    currency: str
    url: str
    shipping: float = 0.0
    seller: str = ""
    seller_country: str = ""
    is_auction: bool = False
    ends_at: Optional[datetime] = None
    item_id: str = ""
    name: str = ""


@dataclass
class Sale:
    """A completed sale (comp) or a guide price."""

    source: str
    key: CardKey
    price: float
    currency: str
    sold_at: datetime
    title: str = ""
    url: str = ""
    item_id: str = ""
    is_guide: bool = False  # True for aggregated guide prices (PriceCharting) rather than a single sale


@dataclass
class Valuation:
    fmv: Optional[float]
    currency: str
    n_comps: int
    dispersion: Optional[float]
    confidence: str  # high | medium | low | none
    method: str
    last_sale: Optional[datetime] = None
    comps_used: list = field(default_factory=list)


@dataclass
class Deal:
    listing: Listing
    valuation: Valuation
    landed_cost: float  # in base currency, incl. shipping + import costs
    discount: float  # 0.25 == 25% below FMV
    savings: float
    score: float
    notes: list = field(default_factory=list)
