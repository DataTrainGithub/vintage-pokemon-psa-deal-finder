"""Command line entry point.

  python -m vdf scan [--demo] [--config config.yaml] [--watchlist watchlist.yaml]
  python -m vdf import-csv FILE.csv          # add sold comps to history
  python -m vdf targets                      # list what will be hunted
  python -m vdf serve [--scan-every 30] [--key SECRET]   # phone-friendly web app on your LAN
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

import yaml

from . import report
from .scanner import build_targets, run
from .sources.csv_import import load_csv
from .store import Store


def _expand_env(obj):
    """Allow ${ENV_VAR} in config so secrets can stay out of the file."""
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    if isinstance(obj, str) and "$" in obj:
        out = os.path.expandvars(obj)
        return "" if re.search(r"\$\{?\w+\}?", out) else out  # unset variable -> empty (= not configured)
    return obj


def load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return _expand_env(yaml.safe_load(p.read_text()) or {})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vdf", description="Vintage Pokémon PSA 9/10 bargain finder")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--watchlist", default="watchlist.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="fetch, value and report deals")
    sc.add_argument("--loop", type=int, default=0, metavar="MIN", help="repeat every MIN minutes")
    ic = sub.add_parser("import-csv", help="import sold comps from CSV into history")
    ic.add_argument("files", nargs="+")
    sub.add_parser("targets", help="list watchlist targets")
    sv = sub.add_parser("serve", help="host the report for your phone, with a Scan-now button")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--scan-every", type=int, default=0, metavar="MIN", help="also scan automatically every MIN minutes")
    sv.add_argument("--key", default=os.environ.get("VDF_KEY", ""), help="access key required in the URL (recommended)")
    for p_ in (sc, sv):
        p_.add_argument("--demo", action="store_true", help="synthetic data, no API keys needed")
        p_.add_argument("--out", default="reports", help="output directory for the web app + CSV")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_yaml(a.config)
    if not cfg and a.config == "config.yaml" and Path("config.example.yaml").exists():
        cfg = load_yaml("config.example.yaml")
    watch = load_yaml(a.watchlist).get("targets", [])
    if not watch:
        sys.exit(f"No targets found in {a.watchlist}")

    if a.cmd == "targets":
        for t in build_targets(watch, tuple(cfg.get("grades", (9, 10)))):
            print(t.key.label(t.name))
        return

    if a.cmd == "import-csv":
        store = Store(cfg.get("database", "data/history.sqlite"))
        for f in a.files:
            sales, listings, rej = load_csv(Path(f))
            n = store.add_sales(sales)
            print(f"{f}: {n} new sales stored ({len(sales)} parsed, {len(listings)} listing rows ignored); rejected: {rej}")
        return

    out = Path(a.out)
    if a.cmd == "serve":
        from .server import serve
        serve(out, lambda: scan_once(cfg, watch, a.demo, out), a.host, a.port, a.scan_every, a.key)
        return
    while True:
        scan_once(cfg, watch, a.demo, out, verbose=True)
        if not a.loop:
            break
        time.sleep(a.loop * 60)


def scan_once(cfg: dict, watch: list, demo: bool, out: Path, verbose: bool = False):
    if demo:
        cfg = {**cfg, "database": str(out / "demo-history.sqlite"), "imports_dir": "__none__"}
        Path(cfg["database"]).unlink(missing_ok=True)
    store = Store(cfg.get("database", "data/history.sqlite"))
    res = run(cfg, watch, demo=demo, store=store)
    base = cfg.get("fx", {}).get("base", "EUR")
    page = report.write_html(res, out, cfg.get("deals", {}), base)
    report.write_csv(res, out / "deals.csv")
    if verbose:
        print(report.console(res))
        print(f"\nReport: {page}  CSV: {out / 'deals.csv'}")
    if not demo:
        n = report.send_alerts(res, cfg.get("alerts", {}), store)
        if n:
            logging.getLogger("vdf").info("%d alert(s) sent", n)
    return res

if __name__ == "__main__":
    main()
