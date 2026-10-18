"""The exact "What changed in the data" rows at the top of compare mode (summary_facts.compare_data)."""
import unittest

from summary_facts import MINUS, compare_data, parse_money


def sheet(price, price_text, pe, target, yield_pct, pnl, urls=(), owned=True):
    facts = {
        "company": {"currency": "USD"},
        "last_price_value": price,
        "D:key_stats": {"last_price": price_text, "pe_ttm": pe, "analyst_target_price": target, "dividend_yield_pct": yield_pct},
        "links": {f"N{i}": {"url": url} for i, url in enumerate(urls, start=1)},
    }
    if owned:
        facts["D:position"] = {"unrealised_gain_or_loss": pnl}
    return facts


OLDER = sheet(200.0, "US$200.00", 30.0, "US$250.00", 0.5, "+US$1,000.00", urls=("a", "b"))
NEWER = sheet(210.0, "US$210.00", 31.5, "US$249.00", 0.5, f"{MINUS}US$500.00", urls=("b", "c", "d"))


def rows(older=OLDER, newer=NEWER):
    return {row["label"]: row for row in compare_data(older, newer)}


class CompareDataTests(unittest.TestCase):
    def test_price_change_is_a_percentage_with_a_tone(self):
        price = rows()["Price"]
        # 200 -> 210 is +5%
        self.assertEqual((price["old"], price["new"], price["change"], price["tone"]), ("US$200.00", "US$210.00", "+5.00%", "gain"))

    def test_pe_and_dividend_yield_changes(self):
        r = rows()
        self.assertEqual(r["P/E (trailing)"]["change"], "+1.50")
        self.assertIsNone(r["P/E (trailing)"]["tone"])  # not a gain or loss for the investor
        self.assertEqual(r["Dividend yield"]["change"], "No change")
        self.assertEqual(r["Dividend yield"]["new"], "0.5%")

    def test_a_small_move_is_shown_but_marked_minor(self):
        # Analyst target 250 -> 249 is −0.4%, under 1%: shown, marked minor, no tone
        target = rows()["Analyst target"]
        self.assertTrue(target["minor"])
        self.assertEqual(target["change"], f"{MINUS}US$1.00 (under 1%)")
        self.assertIsNone(target["tone"])

    def test_pnl_parsed_back_from_saved_text(self):
        # +US$1,000.00 -> −US$500.00 is a change of −US$1,500.00, a loss
        pnl = rows()["Unrealised P&L"]
        self.assertEqual((pnl["change"], pnl["tone"]), (f"{MINUS}US$1,500.00", "loss"))

    def test_new_news_counts_only_links_the_older_summary_didnt_have(self):
        self.assertEqual(rows()["New news items"]["new"], "2")  # c and d

    def test_missing_values_give_no_change(self):
        # A stock not owned then (no position): P&L has no old value, so no change is claimed
        older = sheet(200.0, "US$200.00", None, None, None, None, owned=False)
        r = rows(older=older)
        self.assertIsNone(r["Unrealised P&L"]["old"])
        self.assertIsNone(r["Unrealised P&L"]["change"])
        self.assertIsNone(r["P/E (trailing)"]["change"])

    def test_parse_money(self):
        self.assertEqual(parse_money("US$1,234.50"), 1234.5)
        self.assertEqual(parse_money(f"{MINUS}A$15.00"), -15.0)
        self.assertEqual(parse_money("-A$15.00"), -15.0)
        self.assertEqual(parse_money("+US$3.00"), 3.0)
        self.assertIsNone(parse_money(None))
        self.assertIsNone(parse_money("not available"))


if __name__ == "__main__":
    unittest.main()
