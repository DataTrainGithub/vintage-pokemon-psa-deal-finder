# Vintage PSA Deal Finder

Finds **vintage (WotC 1999–2003) English Pokémon cards in PSA 9 / PSA 10** that are listed well
below their current market value, in a **€1,000–€10,000** window. Cardmarket is the main listing
source, eBay is the second, and fair value comes from sold comps.

```
watchlist.yaml ──► sources ─────────────────► parse & verify ─► history DB ─► fair value ─► landed cost ─► deals
                   Cardmarket (listings)       strict title/      (SQLite,     recency-     + shipping     HTML / CSV
                   eBay (listings + solds)     comment parser     grows every  weighted     + import VAT   Discord /
                   PriceCharting (guide)                          run)         median                      Telegram
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

## Setup

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml          # adjust home_country, thresholds
export MKM_APP_TOKEN=... MKM_APP_SECRET=... MKM_ACCESS_TOKEN=... MKM_ACCESS_SECRET=...
export EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=...
export PRICECHARTING_TOKEN=...              # optional but strongly recommended
python -m vdf scan                          # -> reports/deals.html + deals.csv
python -m vdf scan --loop 30                # rescan every 30 min, alerts only on new deals
python -m vdf scan --demo                   # synthetic data, no keys needed
python -m vdf targets                       # show the 132 card/variant/grade combos being hunted
python -m vdf import-csv sold.csv           # add sold comps (130point, PSA APR, Goldin, …)
python -m unittest                          # 20 tests
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
- `data/history.sqlite` – sold-comp history that builds up across runs

## Known limits

- The connectors follow each portal's published API, but they could not be run against live
  endpoints while this was built. Expect small field-name fixes on the first real run, and run
  with `-v` to see what each source returns.
- English cards only. Japanese vintage would need its own set catalog and parser rules.
- Before you buy, always check the slab photos, the cert number at psacard.com/cert, and the
  seller's feedback. Underpriced slabs are where fakes and scams concentrate.
