"""Fair market value (FMV) per CardKey from sold comps.

- converts everything to the base currency
- keeps sales inside the lookback window
- drops outliers (Tukey fences on the log price) once there are enough comps
- weighted median, weights halve every `half_life_days` so recent sales dominate
- guide prices (PriceCharting) count as a low-weight comp; with no real sales the FMV is
  the guide price with confidence capped at "low"
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .fx import FX
from .models import Sale, Valuation


def weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def _quantile(sorted_vals: list[float], q: float) -> float:
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def fair_value(sales: list[Sale], fx: FX, now: datetime = None, lookback_days: int = 180,
               half_life_days: float = 45, guide_weight: float = 0.5) -> Valuation:
    now = now or datetime.now(timezone.utc)
    real, guides = [], []
    for s in sales:
        age = (now - s.sold_at).total_seconds() / 86400
        if age > lookback_days or age < -1:
            continue
        price = fx.to_base(s.price, s.currency)
        if price <= 0:
            continue
        (guides if s.is_guide else real).append((price, max(age, 0.0), s))

    if len(real) >= 4:
        logs = sorted(math.log(p) for p, _, _ in real)
        q1, q3 = _quantile(logs, 0.25), _quantile(logs, 0.75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr - 0.05, q3 + 1.5 * iqr + 0.05
        real = [r for r in real if lo <= math.log(r[0]) <= hi]

    if not real and not guides:
        return Valuation(None, fx.base, 0, None, "none", "no comps")

    values = [p for p, _, _ in real] + [p for p, _, _ in guides]
    weights = [0.5 ** (age / half_life_days) for _, age, _ in real] + [guide_weight] * len(guides)
    fmv = weighted_median(values, weights)

    n = len(real)
    disp = None
    if n >= 2:
        med = weighted_median([p for p, _, _ in real], [1] * n)
        disp = weighted_median([abs(p - med) for p, _, _ in real], [1] * n) / med
    if n >= 6 and disp is not None and disp <= 0.15:
        conf = "high"
    elif n >= 3 and (disp is None or disp <= 0.30):
        conf = "medium"
    else:
        conf = "low"
    method = f"{n} sales" + (f" + {len(guides)} guide" if guides else "")
    last = max((s.sold_at for _, _, s in real), default=None)
    return Valuation(fmv, fx.base, n, disp, conf, method, last, [s for _, _, s in real + guides])
