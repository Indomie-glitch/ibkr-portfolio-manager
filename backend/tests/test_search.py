import unittest

from ib_async import Contract
from ib_async.contract import ContractDescription

from main import SEARCH_LIMIT, search_results


def found(con_id, symbol, sec_type="STK", exchange="NASDAQ", currency="USD", description="APPLE INC"):
    return ContractDescription(contract=Contract(conId=con_id, symbol=symbol, secType=sec_type, primaryExchange=exchange,
                                                 currency=currency, description=description))


class SearchResultsTest(unittest.TestCase):
    def test_keeps_asx_and_us_stocks_only(self):
        results = search_results([
            found(265598, "AAPL"),
            found(1, "APX", exchange="ASX", currency="AUD", description="APPEN LTD"),
            found(2, "AAPL", exchange="MEXI", currency="MXN"),      # another market
            found(3, "AAPL", sec_type="IND"),                        # not a stock
            ContractDescription(contract=None),
        ], owned_ids={1})
        self.assertEqual([(r["symbol"], r["market"], r["owned"]) for r in results],
                         [("AAPL", "US", False), ("APX", "ASX", True)])
        self.assertEqual(results[1]["exchange"], "ASX")

    def test_name_is_tidied_and_falls_back_to_symbol(self):
        results = search_results([found(1, "KO", exchange="NYSE", description="COCA-COLA CO/THE"),
                                  found(2, "XYZ", description="")], set())
        self.assertEqual(results[0]["name"], "The Coca-Cola Co")
        self.assertEqual(results[1]["name"], "XYZ")

    def test_limit(self):
        results = search_results([found(i, f"S{i}") for i in range(SEARCH_LIMIT + 5)], set())
        self.assertEqual(len(results), SEARCH_LIMIT)


if __name__ == "__main__":
    unittest.main()
