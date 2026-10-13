# Vintage PSA Deal Finder

Finds **vintage (WotC 1999–2003) English Pokémon cards in PSA 9 / PSA 10** that are listed well
below their current market value, in a **€1,000–€10,000** window. Cardmarket is the main listing
source, eBay is the second, and fair value comes from sold comps.

```
watchlist.yaml ──► sources ─────────────────► parse & verify ─► history DB ─► fair value ─► landed cost ─► deals
                   Cardmarket (listings)       strict title/      (SQLite,     recency-     + shipping     phone web app
                   eBay (listings + solds)     comment parser     grows every  weighted     + import VAT   Telegram/Discord
                   PriceCharting (guide)                          run)         median                      push + CSV
                   CSV imports (any solds)
```

## How it decides something is a bargain

1. **Identity is exact.** Each card is a key: *set + number + edition (1st / Shadowless / Unlimited) + PSA grade*.
   A 1st Edition PSA 9 is never compared to an Unlimited PSA 9.
2. **Junk is rejected before pricing.** Rejected listings include reprints (Celebrations, Evolutions,
   Classic Collection), "PSA 10 ready" or raw cards, empty slabs, lots, other graders, and **PSA
   qualifiers (OC/ST/PD/OF/MK/MC)**, which sell far below clean slabs. Non-English cards and
   "Base Set 2" vs "Base Set 2/102" mix-ups are rejected too.
3. **Fair market value (FMV)** is the recency-weighted median of sold comps over the last 180 days.
   A sale's weight halves every 45 days. Outliers such as shill bids and mislabelled items are
   removed. PriceCharting's graded guide price counts as half a sale.
4. **Landed cost** is the price plus shipping. If you live in the EU and the seller is outside
   it (US, UK, Japan), the tool adds **import VAT** (21% for NL/BE, configurable) and a handling fee.
   A $4,000 US card is not a bargain if it costs €4,400 once it reaches you.
5. **A deal** has a landed cost between €1k and €10k and sits at least 20% below FMV.
   - Anything more than 70% below FMV is dropped as "too good to be true".
   - Score = discount × confidence, where confidence comes from comp count and price spread.
   - Auctions are marked, because the current bid is not the final price.

## Using it on your phone

The tool is built to be used from a phone. The scan runs on a computer or server, and you use
the results on the phone.

| | What you get on the phone | How |
|---|---|---|
| **Push alerts** | A Telegram or Discord message for each new deal, showing the discount, delivered price, market value and an **Open listing** button | Set `alerts:` in the config (Telegram bot: talk to @BotFather, get the chat id from @userinfobot) |
| **Web app** | A phone-first page with a deal card per listing, filters (PSA 10/9, Cardmarket/eBay, EU sellers, buy-now only), sort, search and a Market tab. It works offline with the last scan and can be added to your home screen as an app | `python -m vdf serve` (home network) or GitHub Pages (anywhere) |
| **Scan now** | A button in the web app that starts a fresh scan | Only available with `serve` |

**Option A: your PC or a Raspberry Pi at home**
```bash
python -m vdf serve --scan-every 30 --key choose-a-secret
# prints e.g. http://192.168.1.20:8000/?key=choose-a-secret
```
1. Open that URL on your phone while it's on the same Wi-Fi.
2. iPhone: tap Share, then **Add to Home Screen**. Android: open the menu, then **Install app**.
3. The key is remembered, so the home-screen icon opens straight in.

To reach it when you're away from home, use Tailscale or Cloudflare Tunnel. Don't port-forward it.

**Option B: no computer needed (GitHub Actions)**

`.github/workflows/scan.yml` scans every 2 hours in the cloud and sends your alerts.
1. Add your API keys and Telegram details under *Settings → Secrets and variables → Actions*.
2. If you also want the web app on GitHub Pages, set the repository variable `PUBLISH_PAGES=true`
   and choose *Settings → Pages → Source: GitHub Actions*.
3. To scan on demand from your phone, use **Run workflow** in the GitHub mobile app.

Pages on a private repo needs a paid GitHub plan, and anyone who has the page URL can open it.

## Setup

**Getting API keys:** see [docs/API_KEYS.md](docs/API_KEYS.md) for step-by-step instructions for eBay, Cardmarket, PriceCharting, Telegram and Discord.

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml          # adjust home_country, thresholds
export MKM_APP_TOKEN=... MKM_APP_SECRET=... MKM_ACCESS_TOKEN=... MKM_ACCESS_SECRET=...
export EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=...
export PRICECHARTING_TOKEN=...              # optional but strongly recommended
python -m vdf scan                          # -> reports/index.html (phone web app) + deals.csv
python -m vdf scan --loop 30                # rescan every 30 min, alerts only on new deals
python -m vdf scan --demo                   # synthetic data, no keys needed
python -m vdf targets                       # show the 132 card/variant/grade combos being hunted
python -m vdf import-csv sold.csv           # add sold comps (130point, PSA APR, Goldin, …)
python -m vdf serve --demo                  # try the phone app with synthetic data
python -m unittest                          # 24 tests
```

## Data sources: what each one gives you and how to get access

| Source | Used for | Access |
|---|---|---|
| **Cardmarket** (MKM API 2.0) | EU listings. Also the raw TREND price as context. | Create a *Dedicated App* under Account → Settings → API. Cardmarket has limited new API access in recent years, so it may only be granted to some (often professional) accounts. If yours isn't approved, see the fallback below. |
| **eBay Browse API** | Active listings worldwide (fixed price and auctions) | Free developer account at developer.ebay.com |
| **eBay Marketplace Insights** | **Sold** prices (best comp source) | Limited-release API that needs eBay's approval. The tool falls back automatically if it isn't granted. |
| **PriceCharting API** | PSA 9 / PSA 10 guide prices built from eBay solds | Paid subscription (Legendary tier) |
| **CSV import** | Any sold data: 130point, PSA Auction Prices Realized, Goldin/PWCC/Heritage results, your own Cardmarket purchases | Drop CSVs in `imports/` (columns: `date,price,currency,title`) |

**Cardmarket caveat:** Cardmarket has no structured "graded" field for Pokémon. Sellers write
the slab in the comment, e.g. "PSA 9". The tool reads that comment with the same strict parser,
so a listing without a clear PSA grade in its comment is skipped. Cardmarket's own price guide
covers **raw** cards only, so it never sets graded FMV. It appears as a context column.

**No API approval for Cardmarket?** Put the listings you find into `imports/` as rows with
`kind=listing`. They are valued and scored the same way.

## Files

- `watchlist.yaml` – the cards to hunt (Base, Jungle, Fossil, Rocket, Gym, Neo, e-Card key holos). Verify the numbers before relying on an entry.
- `config.example.yaml` – thresholds, VAT, FX, API keys (`${ENV}` placeholders), alerts
- `vdf/parse.py` – title/comment parser and reject rules
- `vdf/valuation.py` – FMV
- `vdf/scoring.py` – landed cost and deal rules
- `vdf/sources/` – one connector per portal
- `vdf/web/` – the phone web app (single page, home-screen installable, offline cache)
- `vdf/server.py` – `serve` command: hosts the app with a Scan-now button and an access key
- `.github/workflows/scan.yml` – scheduled cloud scans, alerts and optional Pages publishing
- `data/history.sqlite` – sold-comp history that builds up across runs

## Known limits

- The connectors follow each portal's published API, but they could not be run against live
  endpoints while this was built. Expect small field-name fixes on the first real run, and run
  with `-v` to see what each source returns.
- English cards only. Japanese vintage would need its own set catalog and parser rules.
- Before you buy, always check the slab photos, the cert number at psacard.com/cert, and the
  seller's feedback. Underpriced slabs are where fakes and scams concentrate.
