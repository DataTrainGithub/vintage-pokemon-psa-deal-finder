"""Console, CSV and mobile-first web app output + Discord/Telegram alerts formatted for phones."""
from __future__ import annotations

import csv
import html
import logging
import shutil
from pathlib import Path

import requests
from jinja2 import Environment

from .catalog import SETS
from .scanner import ScanResult
from .store import Store

log = logging.getLogger(__name__)


def money(v, cur="EUR"):
    if v is None:
        return "—"
    sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(cur, cur + " ")
    return f"{sym}{v:,.0f}"


def console(res: ScanResult, limit: int = 25) -> str:
    lines = [f"Scan {res.started:%Y-%m-%d %H:%M} UTC — {len(res.deals)} deal(s)"]
    if res.deals:
        lines.append(f"{'score':>5} {'disc':>5} {'cost':>8} {'FMV':>8} {'conf':<6} {'src':<15} card")
        for d in res.deals[:limit]:
            v = d.valuation
            lines.append(f"{d.score:5.2f} {d.discount:5.0%} {money(d.landed_cost, v.currency):>8} "
                         f"{money(v.fmv, v.currency):>8} {v.confidence:<6} {d.listing.source[:15]:<15} "
                         f"{d.listing.key.label(d.listing.name)}")
            lines.append(f"{'':>45} {d.listing.url}" + (f"  [{'; '.join(d.notes)}]" if d.notes else ""))
    stats = ", ".join(f"{k}={v}" for k, v in sorted(res.stats.items()))
    lines.append(f"stats: {stats}")
    return "\n".join(lines)


def write_csv(res: ScanResult, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["score", "discount", "landed_cost", "fmv", "currency", "savings", "confidence", "comps",
                    "card", "source", "price", "listing_currency", "shipping", "seller_country", "auction",
                    "url", "title", "notes"])
        for d in res.deals:
            l, v = d.listing, d.valuation
            w.writerow([f"{d.score:.3f}", f"{d.discount:.3f}", f"{d.landed_cost:.2f}", f"{v.fmv:.2f}", v.currency,
                        f"{d.savings:.2f}", v.confidence, v.n_comps, l.key.label(l.name), l.source, l.price,
                        l.currency, l.shipping, l.seller_country, l.is_auction, l.url, l.title, "; ".join(d.notes)])


WEB = Path(__file__).parent / "web"
STATIC = ["manifest.webmanifest", "sw.js", "icon.svg", "icon-180.png", "icon-192.png", "icon-512.png"]
EDITION = {"1st": "1st Edition", "shadowless": "Shadowless", "unlimited": "Unlimited"}


def _card(key, name):
    s = SETS.get(key.set_code)
    return {"name": name or f"#{key.number}", "set": s.name if s else key.set_code, "number": key.number,
            "edition": EDITION.get(key.variant, key.variant), "grade": key.grade}


def _iso(dt):
    return dt.isoformat() if dt else None


def web_data(res: ScanResult, deal_cfg: dict, base: str) -> dict:
    raw = {m.target.key: m.raw_trend for m in res.market}
    deals = []
    for d in res.deals:
        l, v = d.listing, d.valuation
        deals.append({**_card(l.key, l.name), "score": round(d.score, 4), "discount": round(d.discount, 4),
                      "cost": round(d.landed_cost, 2), "fmv": round(v.fmv, 2), "savings": round(d.savings, 2),
                      "conf": v.confidence, "ncomps": v.n_comps, "method": v.method, "last_sale": _iso(v.last_sale),
                      "source": l.source, "country": l.seller_country, "price": l.price, "cur": l.currency,
                      "ship": l.shipping, "auction": l.is_auction, "ends": _iso(l.ends_at), "url": l.url,
                      "title": l.title, "notes": d.notes, "import_vat": any("import VAT" in n for n in d.notes),
                      "raw": raw.get(l.key)})
    market = []
    for m in res.market:
        v, c = m.valuation, m.cheapest
        market.append({**_card(m.target.key, m.target.name), "fmv": round(v.fmv, 2) if v.fmv else None,
                       "conf": v.confidence, "ncomps": v.n_comps, "last_sale": _iso(v.last_sale),
                       "listings": m.listings, "cheapest": round(c.landed_cost, 2) if c else None,
                       "vs": round(c.discount, 4) if c else None, "url": c.listing.url if c else None,
                       "raw": m.raw_trend})
    cfg = {"price_min": 1000, "price_max": 10000, "min_discount": 0.2, **deal_cfg}
    return {"scanned": res.started.isoformat(), "base": base, "deals": deals, "market": market,
            "cfg": {k: cfg[k] for k in ("price_min", "price_max", "min_discount")}}


def write_html(res: ScanResult, out_dir: Path, deal_cfg: dict, base: str) -> Path:
    """Write the phone-friendly web app (index.html + PWA files) into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(autoescape=True)
    page = env.from_string((WEB / "app.html").read_text()).render(data=web_data(res, deal_cfg, base))
    tmp = out_dir / "index.html.tmp"
    tmp.write_text(page)
    tmp.replace(out_dir / "index.html")  # atomic, so a phone never loads a half-written page
    for f in STATIC:
        shutil.copyfile(WEB / f, out_dir / f)
    return out_dir / "index.html"


def _alert_text(d) -> str:
    l, v = d.listing, d.valuation
    c = _card(l.key, l.name)
    src = "Cardmarket" if "cardmarket" in l.source else "eBay" if "ebay" in l.source else l.source
    lines = [f"<b>−{d.discount:.0%} · {html.escape(c['name'])} PSA {c['grade']}</b>",
             f"{html.escape(c['set'])} #{c['number']} · {c['edition']}",
             f"Delivered <b>{money(d.landed_cost, v.currency)}</b> · FMV {money(v.fmv, v.currency)} · save {money(d.savings, v.currency)}",
             f"{src}{' · ' + l.seller_country if l.seller_country else ''} · {v.confidence} confidence ({v.n_comps} sales)"]
    if d.notes:
        lines.append("⚠️ " + html.escape("; ".join(d.notes)))
    return "\n".join(lines)


def send_alerts(res: ScanResult, cfg: dict, store: Store, report_url: str = "") -> int:
    hook = cfg.get("discord_webhook")
    tg_token, tg_chat = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
    if not (hook or (tg_token and tg_chat)):
        return 0
    report_url = report_url or cfg.get("report_url", "")
    min_score = cfg.get("min_score", 0.2)
    ok_conf = {"low": {"low", "medium", "high"}, "medium": {"medium", "high"}, "high": {"high"}}[cfg.get("min_confidence", "medium")]
    sent = 0
    for d in res.deals:
        l = d.listing
        if d.score < min_score or d.valuation.confidence not in ok_conf or store.was_alerted(l.source, l.item_id or l.url, l.price):
            continue
        text = _alert_text(d)
        try:
            if tg_token and tg_chat:
                buttons = [[{"text": "Open listing ↗", "url": l.url}]]
                if report_url:
                    buttons[0].append({"text": "All deals", "url": report_url})
                requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", timeout=15, json={
                    "chat_id": tg_chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
                    "reply_markup": {"inline_keyboard": buttons}}).raise_for_status()
            if hook:
                plain = html.unescape(text.replace("<b>", "**").replace("</b>", "**"))
                title, _, body = plain.partition("\n")
                requests.post(hook, timeout=15, json={"embeds": [{
                    "title": title.strip("*"), "url": l.url, "description": body + (f"\n[All deals]({report_url})" if report_url else ""),
                    "color": 0x157A3C}]}).raise_for_status()
            store.mark_alerted(l.source, l.item_id or l.url, l.price)
            sent += 1
        except Exception as e:
            log.warning("alert failed: %s", e)
    return sent
