"""Console, CSV and self-contained HTML output + optional Discord/Telegram alerts."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

import requests
from jinja2 import Environment

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


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Vintage PSA Deals</title>
<style>
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--good:#15803d;--warn:#b45309;--accent:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;--line:#44403c;--good:#4ade80;--warn:#fbbf24;--accent:#93c5fd}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:1200px;margin:auto}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
.muted{color:var(--muted)}.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-weight:600;cursor:pointer;position:sticky;top:0;background:var(--card)}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.good{color:var(--good);font-weight:600}.warn{color:var(--warn)}a{color:var(--accent)}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;border:1px solid var(--line);font-size:12px}
</style></head><body><main>
<h1>Vintage PSA 9/10 deals</h1>
<div class="muted">Scan {{ res.started.strftime('%Y-%m-%d %H:%M') }} UTC · landed cost {{ money(cfg.price_min) }}–{{ money(cfg.price_max) }} · ≥{{ (cfg.min_discount*100)|round|int }}% under FMV · prices in {{ base }}</div>
<h2>Deals ({{ res.deals|length }})</h2>
<div class="wrap"><table class="sortable"><thead><tr>
<th class="n">Score</th><th class="n">Discount</th><th class="n">Landed cost</th><th class="n">FMV</th><th class="n">Savings</th>
<th>Confidence</th><th>Card</th><th>Source</th><th>Listing</th><th>Notes</th></tr></thead><tbody>
{% for d in res.deals %}<tr>
<td class="n">{{ '%.2f'|format(d.score) }}</td><td class="n good">{{ (d.discount*100)|round|int }}%</td>
<td class="n">{{ money(d.landed_cost, base) }}</td><td class="n">{{ money(d.valuation.fmv, base) }}</td>
<td class="n">{{ money(d.savings, base) }}</td>
<td><span class="pill">{{ d.valuation.confidence }}</span> <span class="muted">{{ d.valuation.method }}</span></td>
<td>{{ d.listing.key.label(d.listing.name) }}</td><td>{{ d.listing.source }}{% if d.listing.seller_country %} · {{ d.listing.seller_country }}{% endif %}</td>
<td><a href="{{ d.listing.url }}" target="_blank" rel="noopener">{{ money(d.listing.price, d.listing.currency) }}{% if d.listing.shipping %} + {{ money(d.listing.shipping, d.listing.currency) }}{% endif %}</a></td>
<td class="warn">{{ d.notes|join('; ') }}</td></tr>
{% else %}<tr><td colspan="10" class="muted">No listings beat the thresholds this run.</td></tr>{% endfor %}
</tbody></table></div>
<h2>Market overview</h2>
<div class="wrap"><table class="sortable"><thead><tr><th>Card</th><th class="n">FMV</th><th>Confidence</th><th class="n">Comps</th>
<th>Last sale</th><th class="n">Listings</th><th class="n">Cheapest landed</th><th class="n">vs FMV</th><th class="n">Raw CM trend</th></tr></thead><tbody>
{% for m in res.market %}<tr><td>{{ m.target.key.label(m.target.name) }}</td><td class="n">{{ money(m.valuation.fmv, base) }}</td>
<td><span class="pill">{{ m.valuation.confidence }}</span></td><td class="n">{{ m.valuation.n_comps }}</td>
<td>{{ m.valuation.last_sale.strftime('%Y-%m-%d') if m.valuation.last_sale else '—' }}</td><td class="n">{{ m.listings }}</td>
<td class="n">{% if m.cheapest %}<a href="{{ m.cheapest.listing.url }}" target="_blank" rel="noopener">{{ money(m.cheapest.landed_cost, base) }}</a>{% else %}—{% endif %}</td>
<td class="n {{ 'good' if m.cheapest and m.cheapest.discount > 0 else '' }}">{{ ('%+d%%'|format((-m.cheapest.discount*100)|round|int)) if m.cheapest else '—' }}</td>
<td class="n">{{ money(m.raw_trend, 'EUR') if m.raw_trend else '—' }}</td></tr>{% endfor %}
</tbody></table></div>
<p class="muted">FMV = recency-weighted median of sold PSA comps (outliers removed), guide prices weighted lower. Always check the slab photo, cert number (psacard.com/cert) and seller feedback before buying.</p>
</main><script>
document.querySelectorAll('table.sortable th').forEach((th,i)=>th.addEventListener('click',()=>{
 const tb=th.closest('table').tBodies[0],rows=[...tb.rows],asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 const val=r=>{const t=r.cells[i]?.innerText||'';const n=parseFloat(t.replace(/[^0-9.+-]/g,''));return isNaN(n)?t:n};
 rows.sort((a,b)=>{const x=val(a),y=val(b);return (x>y?1:x<y?-1:0)*(asc?1:-1)});rows.forEach(r=>tb.appendChild(r));}));
</script></body></html>"""


def write_html(res: ScanResult, path: Path, deal_cfg: dict, base: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {"price_min": 1000, "price_max": 10000, "min_discount": 0.2, **deal_cfg}
    env = Environment(autoescape=True)
    path.write_text(env.from_string(HTML).render(res=res, cfg=cfg, base=base,
                                                 money=lambda v, c=base: money(v, c)))


def send_alerts(res: ScanResult, cfg: dict, store: Store) -> int:
    hook = cfg.get("discord_webhook")
    tg_token, tg_chat = cfg.get("telegram_bot_token"), cfg.get("telegram_chat_id")
    if not (hook or (tg_token and tg_chat)):
        return 0
    min_score = cfg.get("min_score", 0.2)
    ok_conf = {"low": {"low", "medium", "high"}, "medium": {"medium", "high"}, "high": {"high"}}[cfg.get("min_confidence", "medium")]
    sent = 0
    for d in res.deals:
        l = d.listing
        if d.score < min_score or d.valuation.confidence not in ok_conf or store.was_alerted(l.source, l.item_id or l.url, l.price):
            continue
        msg = (f"{l.key.label(l.name)}\n{d.discount:.0%} under FMV ({money(d.landed_cost)} vs {money(d.valuation.fmv)}, "
               f"{d.valuation.confidence} confidence, {d.valuation.method})\n{l.source} · {l.url}")
        try:
            if hook:
                requests.post(hook, json={"content": msg}, timeout=15).raise_for_status()
            if tg_token and tg_chat:
                requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                              json={"chat_id": tg_chat, "text": msg}, timeout=15).raise_for_status()
            store.mark_alerted(l.source, l.item_id or l.url, l.price)
            sent += 1
        except Exception as e:
            log.warning("alert failed: %s", e)
    return sent
