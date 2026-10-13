"""Vintage (WotC era, 1999-2003) English set catalog.

`aliases` are matched against listing titles (longest alias first), `total` is the printed
set size used to recognise "4/102"-style numbers, and `cardmarket` holds the expansion name(s)
Cardmarket uses for the set.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SetInfo:
    code: str
    name: str
    year: int
    total: int
    aliases: tuple
    has_first_ed: bool = True
    has_shadowless: bool = False
    cardmarket: tuple = ()
    search_name: str = ""
    pricecharting: str = ""  # PriceCharting "console-name"


def _s(code, name, year, total, aliases, first=True, shadowless=False, cm=None, search=None, pc=None):
    return SetInfo(
        code=code, name=name, year=year, total=total, aliases=tuple(aliases), has_first_ed=first,
        has_shadowless=shadowless, cardmarket=tuple(cm or (name,)), search_name=search or name,
        pricecharting=pc or f"Pokemon {name}",
    )


SETS: dict[str, SetInfo] = {s.code: s for s in [
    _s("base1", "Base Set", 1999, 102, ["base set", "base"], shadowless=True,
       cm=["Base Set", "Base Set (Shadowless)", "Base Set (1st Edition)"]),
    _s("jungle", "Jungle", 1999, 64, ["jungle"]),
    _s("fossil", "Fossil", 1999, 62, ["fossil"]),
    _s("base2", "Base Set 2", 2000, 130, ["base set 2", "base 2"], first=False),
    _s("rocket", "Team Rocket", 2000, 82, ["team rocket"]),
    _s("gym1", "Gym Heroes", 2000, 132, ["gym heroes"]),
    _s("gym2", "Gym Challenge", 2000, 132, ["gym challenge"]),
    _s("neo1", "Neo Genesis", 2000, 111, ["neo genesis"]),
    _s("neo2", "Neo Discovery", 2001, 75, ["neo discovery"]),
    _s("neo3", "Neo Revelation", 2001, 64, ["neo revelation"]),
    _s("neo4", "Neo Destiny", 2002, 105, ["neo destiny"]),
    _s("si", "Southern Islands", 2001, 18, ["southern islands"], first=False),
    _s("lc", "Legendary Collection", 2002, 110, ["legendary collection"], first=False),
    _s("ecard1", "Expedition", 2002, 165, ["expedition base set", "expedition"], first=False,
       cm=["Expedition Base Set"]),
    _s("ecard2", "Aquapolis", 2003, 147, ["aquapolis"], first=False),
    _s("ecard3", "Skyridge", 2003, 144, ["skyridge"], first=False),
    _s("wotcpromo", "Wizards Black Star Promos", 1999, 53, ["black star promo", "wotc promo", "wizards promo"],
       first=False, search="Black Star Promo", pc="Pokemon Promo"),
]}

# Match longer aliases first so "base set 2" wins over "base set".
ALIASES: list[tuple[str, str]] = sorted(
    ((alias, s.code) for s in SETS.values() for alias in s.aliases), key=lambda x: -len(x[0])
)

TOTAL_TO_SETS: dict[int, list[str]] = {}
for _s_ in SETS.values():
    TOTAL_TO_SETS.setdefault(_s_.total, []).append(_s_.code)
# Team Rocket is printed /82 but Dark Raichu is 83/82; Neo Destiny shinings run to 113/105.
TOTAL_TO_SETS.setdefault(83, []).append("rocket")


def normalise_variant(set_code: str, variant: str) -> str:
    """Sets without 1st Edition prints only have 'unlimited'."""
    s = SETS[set_code]
    if variant == "1st" and not s.has_first_ed:
        return "unlimited"
    if variant == "shadowless" and not s.has_shadowless:
        return "unlimited"
    return variant
