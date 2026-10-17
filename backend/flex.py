"""IBKR Flex Web Service: downloads the Activity Flex Query (docs/flex-query.md) and reads the
open lots (with the date each was bought) and the trades from it.

The trading API (IB Gateway) has no purchase dates, which the 12-month CGT date needs. The Flex
report has them: Open Positions at "Lot" level gives each open lot's open date however old, and
Trades gives the year's buys and sells (a fallback when lots aren't in the query).

Blocking (urllib), so callers run it in a thread. The token appears in request URLs only; error
messages never contain it (and mask_secrets would hide it anyway).
"""
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

SEND_REQUEST_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
REQUEST_TIMEOUT_S = 30
# IBKR prepares the report after the first request; poll for it this many times, this far apart
POLL_ATTEMPTS = 20
POLL_INTERVAL_S = 3

IN_PROGRESS = "1019"
# The Flex Web Service's error codes that someone setting this up is likely to meet
ERRORS = {
    "1003": "The Flex report isn't available yet. Try again in a few minutes.",
    "1012": "The Flex token has expired. Create a new one in Client Portal (docs/flex-query.md).",
    "1014": "The Flex Query ID isn't valid. Check it in Client Portal.",
    "1015": "The Flex token isn't valid. Check it, or create a new one in Client Portal.",
    "1018": "Too many Flex requests. Try again in a few minutes.",
    "1020": "IBKR rejected the Flex request. Check the token and Query ID.",
}


class FlexError(Exception):
    pass


def _get(url):
    """One HTTP GET; replaced in tests."""
    with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_S) as response:
        return response.read()


def _error(root):
    code = (root.findtext("ErrorCode") or "").strip()
    message = (root.findtext("ErrorMessage") or "").strip()
    return code, ERRORS.get(code, f"IBKR Flex error {code}: {message}" if code else "Unexpected answer from IBKR Flex")


def fetch_report(token, query_id, sleep=time.sleep):
    """Downloads the report (XML bytes). Raises FlexError with a message a person can act on."""
    if not token or not query_id:
        raise FlexError("Add the Flex token and Query ID first (docs/flex-query.md).")
    try:
        answer = ET.fromstring(_get(f"{SEND_REQUEST_URL}?t={token}&q={query_id}&v=3"))
    except (OSError, ET.ParseError) as exc:
        raise FlexError(f"Couldn't reach IBKR's Flex service ({exc.__class__.__name__}).") from None
    if (answer.findtext("Status") or "").strip() != "Success":
        raise FlexError(_error(answer)[1])
    code = (answer.findtext("ReferenceCode") or "").strip()
    statement_url = (answer.findtext("Url") or "").strip()

    for _ in range(POLL_ATTEMPTS):
        sleep(POLL_INTERVAL_S)
        try:
            data = _get(f"{statement_url}?q={code}&t={token}&v=3")
            root = ET.fromstring(data)
        except (OSError, ET.ParseError) as exc:
            raise FlexError(f"Couldn't download the Flex report ({exc.__class__.__name__}).") from None
        if root.tag == "FlexQueryResponse":
            return data
        error_code, message = _error(root)
        if error_code != IN_PROGRESS:
            raise FlexError(message)
    raise FlexError("IBKR took too long to prepare the Flex report. Try again later.")


def parse_date(text):
    """Flex dates: "20250115", "2025-01-15", or either with a time after ";", "," or a space."""
    if not text:
        return None
    day = text.strip().replace(",", ";").replace(" ", ";").split(";")[0]
    for pattern in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(day, pattern).date()
        except ValueError:
            continue
    return None


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_report(data):
    """{"lots": [...], "trades": [...]} for stocks, from the report's XML.

    lots:   {con_id, symbol, currency, quantity, cost_price, opened: date}  (open positions by lot)
    trades: {con_id, symbol, currency, quantity, price, traded: date}       (quantity < 0 for sells)
    """
    root = ET.fromstring(data)
    lots, trades = [], []
    for row in root.iter("OpenPosition"):
        if row.get("assetCategory") != "STK" or row.get("levelOfDetail", "").upper() != "LOT":
            continue
        opened = parse_date(row.get("openDateTime"))
        quantity = _number(row.get("position"))
        if opened is None or not quantity:
            continue
        lots.append({
            "con_id": int(row.get("conid")),
            "symbol": row.get("symbol"),
            "currency": row.get("currency"),
            "quantity": quantity,
            "cost_price": _number(row.get("costBasisPrice")),
            "opened": opened,
        })
    for row in root.iter("Trade"):
        if row.get("assetCategory") != "STK":
            continue
        # Only executions; summary rows (by order or by symbol) would count shares twice
        if row.get("levelOfDetail", "EXECUTION").upper() != "EXECUTION":
            continue
        traded = parse_date(row.get("tradeDate") or row.get("dateTime"))
        quantity = _number(row.get("quantity"))
        if traded is None or not quantity:
            continue
        if row.get("buySell", "").upper().startswith("SELL") and quantity > 0:
            quantity = -quantity
        trades.append({
            "con_id": int(row.get("conid")),
            "symbol": row.get("symbol"),
            "currency": row.get("currency"),
            "quantity": quantity,
            "price": _number(row.get("tradePrice")),
            "traded": traded,
        })
    return {"lots": lots, "trades": trades}


def report_date(data):
    """When IBKR generated the report (for "purchase dates as of …"), or None."""
    statement = ET.fromstring(data).find(".//FlexStatement")
    return parse_date(statement.get("whenGenerated")) if statement is not None else None

