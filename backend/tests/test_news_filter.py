"""Which Yahoo headlines count as news about the company (yahoo._fetch_news), with a fake yf.Search."""
import unittest
from unittest import mock

import yahoo

T = 1_760_000_000  # a fixed publish time


def item(title, n, published=T, link=True):
    return {"title": title, "publisher": "Reuters", "link": f"https://example.com/{n}" if link else None,
            "providerPublishTime": published}


class FakeSearch:
    """yf.Search: the company name search gives `by_name`, the symbol search `by_symbol`."""
    by_name, by_symbol, queries = [], [], []

    def __init__(self, query, news_count, max_results):
        FakeSearch.queries.append(query)
        self.news = FakeSearch.by_name if query == FakeSearch.name else FakeSearch.by_symbol


def fetch(results, *, symbol="BHP.AX", ib_symbol="BHP", long_name="BHP Group Limited", short_name="BHP",
          is_asx=True, bare_ticker_ok=True, extra=()):
    FakeSearch.name, FakeSearch.by_name, FakeSearch.by_symbol, FakeSearch.queries = yahoo.search_name(long_name), results, list(extra), []
    with mock.patch.object(yahoo.yf, "Search", FakeSearch):
        return [i["title"] for i in yahoo._fetch_news(symbol, ib_symbol, long_name, short_name, is_asx, bare_ticker_ok)]


class SearchNameTests(unittest.TestCase):
    def test_legal_suffixes_are_dropped(self):
        self.assertEqual(yahoo.search_name("Telstra Group Limited"), "Telstra Group")
        self.assertEqual(yahoo.search_name("Apple Inc."), "Apple")
        self.assertEqual(yahoo.search_name("Commonwealth Bank of Australia"), "Commonwealth Bank of Australia")
        self.assertEqual(yahoo.search_name("Limited"), "Limited")  # never down to nothing


class NewsFilterTests(unittest.TestCase):
    def test_headlines_must_name_the_company(self):
        titles = fetch([
            item("BHP Group lifts copper output", 1),
            item("Iron ore price slips in Asia", 2),  # tagged to BHP by Yahoo, but doesn't name it
            item("Miners rally as bhp group gains", 3),  # names ignore case
        ])
        self.assertEqual(titles, ["BHP Group lifts copper output", "Miners rally as bhp group gains"])

    def test_tickers_match_exactly(self):
        # "ASX:BHP" and "BHP.AX" count; the bare ticker counts only when allowed
        results = [item("Shares in ASX:BHP rise", 1), item("BHP.AX hits a record", 2), item("Why BHP fell today", 3)]
        self.assertEqual(len(fetch(results)), 3)
        # Bare ticker not allowed (the US company with this ticker is a different company: APA)
        apa = [item("APA Corporation beats estimates", 1), item("APA Group wins pipeline deal", 2), item("ASX:APA steady", 3)]
        self.assertEqual(fetch(apa, symbol="APA.AX", ib_symbol="APA", long_name="APA Group", short_name="APA Group",
                               bare_ticker_ok=False), ["APA Group wins pipeline deal", "ASX:APA steady"])

    def test_lowercase_ticker_words_dont_count(self):
        # "Telstra" is the name; the ticker TLS must be in capitals ("tls" in a word like a URL path doesn't count)
        titles = fetch([item("TLS shares climb", 1), item("Why tls certificates expire", 2)],
                       symbol="TLS.AX", ib_symbol="TLS", long_name="Telstra Group Limited", short_name="Telstra")
        self.assertEqual(titles, ["TLS shares climb"])

    def test_repeats_and_updates_are_dropped(self):
        titles = fetch([
            item("BHP Group to sell nickel unit", 1, published=T + 60),
            item("UPDATE 1: BHP Group to sell nickel unit", 2),
            item("BHP Group to sell nickel unit!", 3),
        ])
        self.assertEqual(titles, ["BHP Group to sell nickel unit"])

    def test_items_without_a_title_or_link_are_skipped(self):
        self.assertEqual(fetch([item("", 1), item("BHP Group news", 2, link=False)]), [])

    def test_newest_first_and_at_most_ten(self):
        results = [item(f"BHP Group story {i}", i, published=T + i) for i in range(15)]
        titles = fetch(results)
        self.assertEqual(len(titles), 10)
        self.assertEqual(titles[0], "BHP Group story 14")

    def test_few_name_results_add_a_symbol_search(self):
        titles = fetch([item("BHP Group A", 1)], extra=[item("BHP Group B", 2, published=T + 1)])
        self.assertEqual(FakeSearch.queries, ["BHP Group", "BHP.AX"])
        self.assertEqual(titles, ["BHP Group B", "BHP Group A"])
        # Five or more from the name search: no second search
        fetch([item(f"BHP Group {i}", i) for i in range(5)])
        self.assertEqual(FakeSearch.queries, ["BHP Group"])


if __name__ == "__main__":
    unittest.main()
