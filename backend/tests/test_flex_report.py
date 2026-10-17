"""Tests for the Flex report client (run from backend/: python -m unittest discover tests)."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flex_report as flex  # noqa: E402

# A trimmed Activity Flex Query report in IBKR's XML layout: two lots of one stock, one sold-out
# stock, an option (ignored), executions and a per-order summary row (ignored)
REPORT = b"""<FlexQueryResponse queryName="Portfolio Manager lots" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="DU1234567" fromDate="20251017" toDate="20261016" period="Last365CalendarDays" whenGenerated="20261017;101500">
<OpenPositions>
<OpenPosition assetCategory="STK" symbol="TLS" conid="4081863" currency="AUD" position="60" costBasisPrice="4.9" openDateTime="20250115;093000" levelOfDetail="LOT" />
<OpenPosition assetCategory="STK" symbol="TLS" conid="4081863" currency="AUD" position="40" costBasisPrice="4.99" openDateTime="2026-03-02, 10:01:00" levelOfDetail="LOT" />
<OpenPosition assetCategory="STK" symbol="TLS" conid="4081863" currency="AUD" position="100" costBasisPrice="4.94" openDateTime="" levelOfDetail="SUMMARY" />
<OpenPosition assetCategory="OPT" symbol="AAPL 261218C00200000" conid="99" currency="USD" position="1" costBasisPrice="5" openDateTime="20260601;120000" levelOfDetail="LOT" />
</OpenPositions>
<Trades>
<Trade assetCategory="STK" symbol="TLS" conid="4081863" currency="AUD" tradeDate="20260302" buySell="BUY" quantity="40" tradePrice="4.99" levelOfDetail="EXECUTION" />
<Trade assetCategory="STK" symbol="CBA" conid="4036818" currency="AUD" tradeDate="20260410" buySell="SELL" quantity="-5" tradePrice="160.2" levelOfDetail="EXECUTION" />
<Trade assetCategory="STK" symbol="CBA" conid="4036818" currency="AUD" tradeDate="20260410" buySell="SELL" quantity="-5" tradePrice="160.2" levelOfDetail="ORDER" />
<Trade assetCategory="STK" symbol="BHP" conid="4036812" currency="AUD" tradeDate="2026-05-20" buySell="BUY" quantity="10" tradePrice="44.1" />
</Trades>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>"""

SEND_OK = b"""<FlexStatementResponse timestamp="17 October, 2026 10:15 AM EDT">
<Status>Success</Status><ReferenceCode>1234567890</ReferenceCode>
<Url>https://example.test/GetStatement</Url></FlexStatementResponse>"""
IN_PROGRESS = b"""<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage></FlexStatementResponse>"""
EXPIRED = b"""<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode>
<ErrorMessage>Token has expired.</ErrorMessage></FlexStatementResponse>"""


class FakeService:
    """Stands in for IBKR: answers each GET with the next canned response."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FetchTests(unittest.TestCase):
    def fetch(self, *answers):
        service = FakeService(*answers)
        original = flex._get
        flex._get = service
        try:
            return flex.fetch_report("TOKEN123456", "987", sleep=lambda s: None), service
        finally:
            flex._get = original

    def test_waits_while_ibkr_prepares_the_report(self):
        data, service = self.fetch(SEND_OK, IN_PROGRESS, IN_PROGRESS, REPORT)
        self.assertEqual(data, REPORT)
        self.assertEqual(len(service.urls), 4)
        self.assertIn("q=1234567890", service.urls[-1])

    def test_explains_an_expired_token_without_showing_it(self):
        with self.assertRaises(flex.FlexError) as caught:
            self.fetch(EXPIRED)
        self.assertIn("expired", str(caught.exception))
        self.assertNotIn("TOKEN123456", str(caught.exception))

    def test_network_failure_is_a_flex_error(self):
        with self.assertRaises(flex.FlexError):
            self.fetch(OSError("no network"))

    def test_gives_up_after_the_last_poll(self):
        with self.assertRaises(flex.FlexError) as caught:
            self.fetch(SEND_OK, *[IN_PROGRESS] * flex.POLL_ATTEMPTS)
        self.assertIn("too long", str(caught.exception))

    def test_needs_token_and_query(self):
        with self.assertRaises(flex.FlexError):
            flex.fetch_report("", "987")


class ParseTests(unittest.TestCase):
    def test_reads_stock_lots_with_their_dates(self):
        lots = flex.parse_report(REPORT)["lots"]
        self.assertEqual([(l["quantity"], l["opened"]) for l in lots], [(60, date(2025, 1, 15)), (40, date(2026, 3, 2))])
        self.assertEqual(lots[0]["con_id"], 4081863)
        self.assertEqual(lots[0]["cost_price"], 4.9)

    def test_reads_executions_with_sells_negative(self):
        trades = flex.parse_report(REPORT)["trades"]
        self.assertEqual([(t["symbol"], t["quantity"], t["traded"]) for t in trades], [
            ("TLS", 40, date(2026, 3, 2)), ("CBA", -5, date(2026, 4, 10)), ("BHP", 10, date(2026, 5, 20)),
        ])

    def test_cgt_dates_come_from_the_trade_date_not_settlement(self):
        # Bought Tuesday 30 Jun 2026, settled (T+2) Thursday 2 Jul: the ATO counts from the
        # contract (trade) date, so the discount applies from 1 Jul 2027, not 3 Jul 2027
        import lots
        report = flex.parse_report(b"""<FlexQueryResponse><FlexStatements><FlexStatement>
<OpenPositions><OpenPosition assetCategory="STK" symbol="X" conid="1" currency="AUD" position="5" costBasisPrice="1"
 openDateTime="20260630;150000" settleDate="20260702" levelOfDetail="LOT" /></OpenPositions>
<Trades><Trade assetCategory="STK" symbol="X" conid="1" currency="AUD" tradeDate="20260630" settleDateTarget="20260702"
 dateTime="20260630;150000" buySell="BUY" quantity="5" tradePrice="1" levelOfDetail="EXECUTION" /></Trades>
</FlexStatement></FlexStatements></FlexQueryResponse>""")
        self.assertEqual(report["lots"][0]["opened"], date(2026, 6, 30))
        self.assertEqual(report["trades"][0]["traded"], date(2026, 6, 30))
        self.assertEqual(lots.cgt_discount_date(report["lots"][0]["opened"]), date(2027, 7, 1))

    def test_date_formats(self):
        for text in ("20250115", "2025-01-15", "20250115;093000", "2025-01-15, 09:30:00", "2025-01-15 09:30:00"):
            self.assertEqual(flex.parse_date(text), date(2025, 1, 15), text)
        self.assertIsNone(flex.parse_date(""))
        self.assertIsNone(flex.parse_date("15/01/2025"))

    def test_report_date(self):
        self.assertEqual(flex.report_date(REPORT), date(2026, 10, 17))


if __name__ == "__main__":
    unittest.main()
