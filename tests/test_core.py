import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from vdf.fx import FX
from vdf.models import CardKey, Listing, Sale, Target
from vdf.parse import parse_title
from vdf.scanner import build_targets, run
from vdf.scoring import is_deal, landed_cost, score
from vdf.sources.cardmarket import Cardmarket, oauth_header
from vdf.sources.csv_import import load_csv
from vdf.sources.ebay import Ebay
from vdf.sources.pricecharting import PriceCharting
from vdf.store import Store
from vdf.valuation import fair_value

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
FXR = FX("EUR", {"USD": 0.9}, live=False)
ZARD_SL9 = CardKey("base1", "4", "shadowless", 9)


class ParseTests(unittest.TestCase):
    def ok(self, title, key, **kw):
        res = parse_title(title, **kw)
        self.assertEqual(res.key, key, f"{title!r}: {res.reason}")

    def bad(self, title, **kw):
        res = parse_title(title, **kw)
        self.assertIsNone(res.key, f"{title!r} should be rejected")
        return res.reason

    def test_common_titles(self):
        self.ok("1999 Pokemon Base Set Shadowless Charizard #4 Holo PSA 9 MINT", ZARD_SL9)
        self.ok("Charizard 4/102 Shadowless Holo Rare PSA 9", ZARD_SL9)
        self.ok("Blastoise 1st Edition Base Set 2/102 PSA GEM MINT 10", CardKey("base1", "2", "1st", 10))
        self.ok("2000 Pokemon Team Rocket 1st Ed Dark Charizard #4 PSA 10", CardKey("rocket", "4", "1st", 10))
        self.ok("Dark Raichu 83/82 1st Edition PSA 9", CardKey("rocket", "83", "1st", 9))
        self.ok("Shining Charizard Neo Destiny 107/105 1st Edition PSA 9", CardKey("neo4", "107", "1st", 9))
        self.ok("Charizard Expedition 6/165 Holo PSA 10", CardKey("ecard1", "6", "unlimited", 10))

    def test_base_set_2_not_base_set(self):
        self.ok("Pokemon Base Set 2 Charizard 4/130 PSA 9", CardKey("base2", "4", "unlimited", 9))

    def test_rejections(self):
        self.assertEqual(self.bad("Charizard Base Set Shadowless 4/102 PSA 9 (OC)"), "PSA qualifier")
        self.assertEqual(self.bad("Charizard Base Set Shadowless 4/102 PSA 9 OC"), "PSA qualifier")
        self.bad("Charizard Celebrations Classic Collection Base Set 4/102 PSA 10")
        self.bad("Charizard Base Set 4/102 PSA 10 ready raw")
        self.bad("Charizard Base Set Shadowless 4/102 BGS 9.5")
        self.bad("Charizard Base Set Shadowless 4/102 PSA 8")
        self.bad("Japanese Charizard Base Set No. 006 PSA 10")
        self.bad("Charizard Base Set 4/102 PSA 9")  # edition not stated, discovery mode is conservative

    def test_word_of_is_not_a_qualifier(self):
        self.ok("King of the holos Charizard Base Set Shadowless 4/102 PSA 9", ZARD_SL9)

    def test_hint_fills_gaps_but_never_overrides(self):
        self.ok("Charizard Shadowless PSA 9 Holo", ZARD_SL9, hint=ZARD_SL9)
        self.bad("Charizard Base Set 4/102 PSA 9", hint=ZARD_SL9)  # unlimited != shadowless
        self.bad("Charizard Base Set 2 4/130 PSA 9", hint=ZARD_SL9)
        self.bad("Blastoise Base Set Shadowless 2/102 PSA 9", hint=ZARD_SL9)

    def test_cert_number_not_card_number(self):
        self.ok("Charizard Shadowless Base Set PSA 9 cert #81234567 #4", ZARD_SL9)


class ValuationTests(unittest.TestCase):
    def sale(self, price, days, cur="EUR", guide=False):
        return Sale("t", ZARD_SL9, price, cur, NOW - timedelta(days=days), is_guide=guide)

    def test_outlier_removed_and_confidence(self):
        sales = [self.sale(p, d) for p, d in [(5000, 5), (5100, 10), (4900, 20), (5050, 30), (5200, 40),
                                               (4950, 50), (15000, 3), (900, 4)]]
        v = fair_value(sales, FXR, NOW)
        self.assertAlmostEqual(v.fmv, 5000, delta=150)
        self.assertEqual(v.n_comps, 6)
        self.assertEqual(v.confidence, "high")

    def test_recency_weighting(self):
        sales = [self.sale(4000, 170), self.sale(4000, 160), self.sale(6000, 2), self.sale(6000, 5)]
        self.assertEqual(fair_value(sales, FXR, NOW).fmv, 6000)

    def test_lookback_and_currency(self):
        v = fair_value([self.sale(1000, 400), self.sale(1000, 1, "USD")], FXR, NOW)
        self.assertEqual(v.n_comps, 1)
        self.assertAlmostEqual(v.fmv, 900)
        self.assertEqual(v.confidence, "low")

    def test_guide_only(self):
        v = fair_value([self.sale(3000, 0, "USD", guide=True)], FXR, NOW)
        self.assertAlmostEqual(v.fmv, 2700)
        self.assertEqual((v.n_comps, v.confidence), (0, "low"))

    def test_no_data(self):
        self.assertIsNone(fair_value([], FXR, NOW).fmv)


class ScoringTests(unittest.TestCase):
    cfg = {"home_country": "NL", "import_vat_rate": 0.21, "import_handling_fee": 20,
           "price_min": 1000, "price_max": 10000, "min_discount": 0.2}

    def lst(self, price, cur="EUR", country="DE", ship=0.0):
        return Listing("x", ZARD_SL9, "t", price, cur, "u", shipping=ship, seller_country=country)

    def test_import_vat_for_us_seller(self):
        cost, notes = landed_cost(self.lst(1000, "USD", "US", 50), FXR, self.cfg)
        self.assertAlmostEqual(cost, 1050 * 0.9 * 1.21 + 20)
        self.assertTrue(notes)

    def test_no_vat_inside_eu(self):
        self.assertEqual(landed_cost(self.lst(1000), FXR, self.cfg)[0], 1000)

    def test_deal_window(self):
        v = fair_value([Sale("t", ZARD_SL9, 5000, "EUR", NOW - timedelta(days=i)) for i in range(8)], FXR, NOW)
        self.assertTrue(is_deal(score(self.lst(3500), v, FXR, self.cfg), self.cfg))
        self.assertFalse(is_deal(score(self.lst(4500), v, FXR, self.cfg), self.cfg))  # only 10% off
        self.assertFalse(is_deal(score(self.lst(900), v, FXR, self.cfg), self.cfg))  # under price_min / too good


class OAuthTest(unittest.TestCase):
    def test_reference_vector(self):
        # Twitter's published OAuth 1.0a signing example.
        hdr = oauth_header(
            "POST", "https://api.twitter.com/1.1/statuses/update.json",
            {"include_entities": "true", "status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
            "xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
            "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
            nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", ts="1318622958")
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', hdr)
        self.assertTrue(hdr.startswith('OAuth realm="https://api.twitter.com/1.1/statuses/update.json"'))


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.text = data, status, str(data)

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class SourceParsingTests(unittest.TestCase):
    target = Target(ZARD_SL9, "Charizard")

    def test_cardmarket_articles(self):
        cm = Cardmarket({"enabled": True, "app_token": "a", "app_secret": "b", "access_token": "c",
                         "access_secret": "d", "min_request_interval": 0})
        products = {"product": [
            {"idProduct": 1, "enName": "Charizard", "expansionName": "Base Set (Shadowless)", "number": "4",
             "website": "/en/Pokemon/Products/Singles/Base-Set-Shadowless/Charizard"},
            {"idProduct": 2, "enName": "Charizard", "expansionName": "Base Set", "number": "4"},
            {"idProduct": 3, "enName": "Charizard", "expansionName": "Base Set 2", "number": "4"}]}
        articles = {"article": [
            {"idArticle": 11, "price": 4200.0, "comments": "PSA 9 Mint, perfect centering",
             "seller": {"username": "kartenhaus", "address": {"country": "DE"}}},
            {"idArticle": 12, "price": 3000.0, "comments": "PSA 8"},
            {"idArticle": 13, "price": 1500.0, "comments": "raw, PSA 9 candidate"},
            {"idArticle": 14, "price": 900.0, "comments": ""}]}
        calls = []

        def fake_api(path, params=None):
            calls.append(path)
            return products if path == "products/find" else articles

        with mock.patch.object(cm, "_api", side_effect=fake_api):
            out = cm.listings(self.target)
        self.assertEqual(calls, ["products/find", "articles/1"])
        self.assertEqual([(l.item_id, l.price, l.seller_country) for l in out], [("11", 4200.0, "DE")])
        self.assertIn("Base-Set-Shadowless", out[0].url)

    def test_ebay_browse(self):
        eb = Ebay({"enabled": True, "client_id": "x", "client_secret": "y", "min_request_interval": 0})
        items = {"itemSummaries": [
            {"itemId": "v1|1", "title": "Charizard Base Set Shadowless 4/102 PSA 9 MINT",
             "price": {"value": "5200.00", "currency": "USD"}, "buyingOptions": ["FIXED_PRICE"],
             "shippingOptions": [{"shippingCost": {"value": "25.00", "currency": "USD"}}],
             "itemLocation": {"country": "US"}, "itemWebUrl": "https://ebay/1"},
            {"itemId": "v1|2", "title": "Charizard Base Set Shadowless 4/102 PSA 9 (OC)",
             "price": {"value": "2500.00", "currency": "USD"}, "buyingOptions": ["FIXED_PRICE"]},
            {"itemId": "v1|3", "title": "Charizard Shadowless 4/102 PSA 9", "buyingOptions": ["AUCTION"],
             "currentBidPrice": {"value": "3100", "currency": "USD"}, "itemEndDate": "2026-10-02T18:00:00.000Z"}]}
        with mock.patch.object(eb, "_auth", return_value={}), \
                mock.patch.object(eb, "_get", return_value=Resp(items)):
            out = eb.listings(self.target)
        self.assertEqual([l.item_id for l in out], ["v1|1", "v1|3"])
        self.assertEqual(out[0].shipping, 25.0)
        self.assertTrue(out[1].is_auction)
        self.assertEqual(out[1].price, 3100.0)

    def test_pricecharting_match(self):
        pc = PriceCharting({"enabled": True, "token": "t", "min_request_interval": 0})
        prods = {"products": [
            {"id": 1, "product-name": "Charizard #4", "console-name": "Pokemon Base Set 2", "graded-price": 50000},
            {"id": 2, "product-name": "Charizard [1st Edition] #4", "console-name": "Pokemon Base Set", "graded-price": 9000000},
            {"id": 3, "product-name": "Charizard #4", "console-name": "Pokemon Base Set Shadowless", "graded-price": 650000},
            {"id": 4, "product-name": "Charizard #4", "console-name": "Pokemon Base Set", "graded-price": 120000}]}
        with mock.patch.object(pc, "_get", return_value=Resp(prods)):
            sl = pc.sales(self.target)
            unl = pc.sales(Target(CardKey("base1", "4", "unlimited", 9), "Charizard"))
        self.assertEqual((sl[0].price, sl[0].is_guide), (6500.0, True))
        self.assertEqual(unl[0].price, 1200.0)


class CsvAndPipelineTests(unittest.TestCase):
    def test_csv_and_full_scan(self):
        with tempfile.TemporaryDirectory() as d:
            imp = Path(d) / "imports"
            imp.mkdir()
            rows = ["date,price,currency,title"]
            rows += [f"2026-09-{10 + i:02d},\"$5,{i}00.00\",USD,Charizard Base Set Shadowless 4/102 PSA 9" for i in range(6)]
            rows += ["2026-09-20,4800,EUR,Charizard Base Set 4/102 PSA 9 OC",
                     "2026-09-21,3100,EUR,\"Charizard Base Set Shadowless 4/102 PSA 9\",",
                     "2026-09-22,999,EUR,Charizard Shadowless Base Set PSA 9 cert #1234",
                     ]
            (imp / "sold.csv").write_text("\n".join(rows[:-2]) + "\n")
            sales, _, rej = load_csv(imp / "sold.csv")
            self.assertEqual(len(sales), 6)
            self.assertEqual(rej, {"PSA qualifier": 1})
            self.assertAlmostEqual(sales[1].price, 5100.0)

            (imp / "listings.csv").write_text(
                "date,price,currency,title,kind,seller_country,url\n"
                "2026-09-30,3300,EUR,Charizard Base Set Shadowless 4/102 PSA 9,listing,NL,https://cm/1\n"
                "2026-09-30,4500,EUR,Charizard Base Set Shadowless 4/102 PSA 9,listing,NL,https://cm/2\n")
            cfg = {"database": str(Path(d) / "h.sqlite"), "imports_dir": str(imp),
                   "fx": {"base": "EUR", "live": False, "fallback_rates": {"USD": 0.9}},
                   "deals": {"home_country": "NL", "min_discount": 0.2}}
            res = run(cfg, [{"name": "Charizard", "set": "base1", "number": 4, "variants": ["shadowless"],
                             "grades": [9]}], store=Store(cfg["database"]), now=NOW)
            self.assertEqual([d.listing.url for d in res.deals], ["https://cm/1"])
            self.assertAlmostEqual(res.deals[0].valuation.fmv, 4.6e3, delta=200)

    def test_watchlist_expansion(self):
        t = build_targets([{"name": "Charizard", "set": "ecard1", "number": 6, "variants": ["1st"]},
                           {"name": "Charizard", "set": "base1", "number": "04", "variants": ["1st", "shadowless"]}])
        self.assertEqual([x.key.id for x in t], [
            "ecard1|6|unlimited|PSA9|EN", "ecard1|6|unlimited|PSA10|EN",
            "base1|4|1st|PSA9|EN", "base1|4|1st|PSA10|EN", "base1|4|shadowless|PSA9|EN", "base1|4|shadowless|PSA10|EN"])


if __name__ == "__main__":
    unittest.main()
