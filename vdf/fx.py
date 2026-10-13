"""Currency conversion. Live ECB rates via frankfurter.app, falling back to config values."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

# Rough EUR-based defaults so a scan never crashes on a missing rate; config/live rates override.
DEFAULT_EUR = {"USD": 0.86, "GBP": 1.16, "JPY": 0.0057, "CHF": 1.07, "CAD": 0.62, "AUD": 0.57}


class FX:
    def __init__(self, base: str, fallback: dict, live: bool = True):
        self.base = base.upper()
        # fallback: units of BASE per 1 unit of currency, e.g. {"USD": 0.86}
        self.rates = dict(DEFAULT_EUR) if self.base == "EUR" else {}
        self.rates.update({k.upper(): float(v) for k, v in (fallback or {}).items()})
        self.rates[self.base] = 1.0
        if live:
            try:
                r = requests.get("https://api.frankfurter.app/latest", params={"from": self.base}, timeout=10)
                r.raise_for_status()
                for cur, per_base in r.json()["rates"].items():
                    self.rates[cur] = 1.0 / per_base
            except Exception as e:  # network blocked, API down: config rates are good enough
                log.info("Live FX unavailable (%s); using configured rates", e)

    def to_base(self, amount: float, currency: str) -> float:
        cur = currency.upper()
        if cur not in self.rates:
            raise KeyError(f"No FX rate for {cur}; add it under fx.fallback_rates in config")
        return amount * self.rates[cur]
