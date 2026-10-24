"""Trading (Milestone 6): status, preview, place, change and cancel orders, the orders list and
the order status stream."""
import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import borrowing
import config
import fx
import trading
from ib_core import build_quote, clean, fetch_tickers, get_contract_info, ib, require_ib
from names import display_name
from secrets_guard import mask_secrets
import web
from web import check_origin, next_or_none, sse
from routers.positions import account

router = APIRouter()

@router.get("/trading/status")
def trading_status():
    """Paper or live account, whether orders are allowed and why not, and the order limits."""
    accounts = ib.managedAccounts() if ib.isConnected() else []
    return trading.status(accounts)

class OrderRequest(BaseModel):
    con_id: int
    action: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    order_type: Literal["MKT", "LMT"]
    limit_price: float | None = None
    tif: Literal["DAY", "GTC"] = "DAY"

# The last price each stock was valued at, to value open market orders (they have no limit price)
last_prices = {}

async def open_buy_commitments(exclude_order_id=None):
    """What open buy orders (from every client: this app, TWS, mobile) will use when they fill, per
    currency, for the borrowing check: {currency: cost with fees}. exclude_order_id: an order being
    changed, which the new numbers replace."""
    try:
        await asyncio.wait_for(ib.reqAllOpenOrdersAsync(), timeout=5)
    except Exception:  # IB slow or refused: use the orders this connection already knows
        pass
    pending = [t for t in ib.openTrades()
               if t.contract.secType == "STK" and t.order.action == "BUY" and t.contract.currency
               and t.order.orderId != exclude_order_id]

    async def value_of(trade):
        left = trade.remaining()
        price = trade.order.lmtPrice if trade.order.orderType in ("LMT", "STP LMT") and trade.order.lmtPrice else None
        con_id = trade.contract.conId
        price = price or last_prices.get(con_id) or next(
            (clean(i.marketPrice) for i in ib.portfolio() if i.contract.conId == con_id), None)
        if not price:
            try:
                price = (await build_quote(con_id, None))["last"]
            except Exception:
                price = None
            if price:
                # Remembered, so the next preview doesn't ask IB for history again (it has a limit)
                last_prices[con_id] = price
        return trade.contract.currency, left * price if price and left > 0 else None

    values = await asyncio.gather(*(value_of(t) for t in pending))
    return borrowing.reserved_by_open_buys([(currency, value) for currency, value in values if value])

async def checked_order(order: OrderRequest, replacing_order_id=None):
    """Everything an order needs before IB sees it: the contract, the price it's valued at, the
    guardrail status and the problems that stop it (trading.check_order). replacing_order_id: the
    open order this one changes, which doesn't count against the cash."""
    contract, _ = await get_contract_info(order.con_id)
    if contract is None or contract.secType != "STK":
        raise HTTPException(status_code=404, detail="Unknown stock")
    if order.order_type == "LMT" and order.limit_price:
        price = order.limit_price
    else:
        tickers = await fetch_tickers([contract])
        price = (await build_quote(order.con_id, tickers.get(order.con_id)))["last"]
    if price:
        last_prices[order.con_id] = price
    account_data = await account()
    base = account_data["currency"]
    # A stock in a currency the account has no cash in has no ledger rate; fx finds one (#270)
    fx_rate = await fx.rate_to_base(contract.currency, base, account_data["fx_rates"])
    held = next((item.position for item in ib.portfolio() if item.contract.conId == order.con_id), 0)
    status = trading.status(ib.managedAccounts())
    problems, value, value_base = trading.check_order(order.model_dump(), price, fx_rate, held, status)
    # Would it borrow from IBKR? Blocked unless switched off for this account (#289)
    # after what open buy orders will use (cash only drops when they fill)
    reserved = await open_buy_commitments(replacing_order_id) if order.action == "BUY" else {}
    borrow = borrowing.borrow_needed(order.action, value, contract.currency,
                                     account_data.get("cash_by_currency", {}), base, reserved)
    if borrow:
        blocked = not borrowing.borrowing_allowed(account_id())
        borrow = {**borrow, "blocked": blocked, "message": borrowing.borrow_message(borrow, base, blocked)}
        if blocked:
            problems.append(borrow["message"])
    return {
        "contract": contract, "price": price, "held": held, "status": status, "problems": problems,
        "value": value, "value_base": value_base, "base_currency": base, "borrow": borrow,
    }

def account_id():
    """The IBKR account the borrowing setting belongs to (Gateway logs in to one at a time)."""
    accounts = ib.managedAccounts() if ib.isConnected() else []
    return accounts[0] if accounts else None

class BorrowingChange(BaseModel):
    block: bool
    # Development only: switching blocking off needs this typed, as BORROW
    confirm: str | None = None

@router.get("/trading/borrowing", dependencies=[Depends(require_ib)])
def borrowing_setting():
    """Whether orders that would borrow from IBKR are blocked for this account (on by default).
    change_here: the browser version changes it with POST below; the Mac app through its own
    Touch ID / Mac password prompt."""
    account = account_id()
    return {"account_id": account, "block": not borrowing.borrowing_allowed(account), "change_here": not config.IN_APP}

@router.post("/trading/borrowing", dependencies=[Depends(require_ib)])
def change_borrowing(change: BorrowingChange, request: Request):
    """Development only (the Mac app changes it over stdin after Touch ID): turns blocking on, or
    off with confirm "BORROW"."""
    check_origin(request)
    if config.IN_APP:
        raise HTTPException(status_code=403, detail="In the app, change this in Settings.")
    if not change.block and (change.confirm or "").strip() != "BORROW":
        raise HTTPException(status_code=400, detail="Type BORROW to allow borrowing.")
    account = account_id()
    if not account:
        raise HTTPException(status_code=503, detail="IB Gateway is not connected")
    borrowing.save_allowed(account, not change.block)
    return borrowing_setting()

@router.post("/orders/preview", dependencies=[Depends(require_ib)])
async def preview_order(order: OrderRequest, request: Request):
    """What an order would cost (IB's what-if: commission and margin impact), without sending it.
    A preview that passes every check comes with the confirmation token POST /orders needs."""
    check_origin(request)
    checked = await checked_order(order)
    contract = checked["contract"]
    what_if = None
    token = None
    if not checked["problems"]:
        try:
            state = await asyncio.wait_for(ib.whatIfOrderAsync(contract, trading.build_order(order.model_dump())), timeout=10)
            what_if = trading.what_if_summary(state)
            # Placing this exact order needs this token (single use, 2 minutes)
            token = confirmation_tokens.issue(order.con_id, order.model_dump(), time.monotonic())
        except asyncio.TimeoutError:
            checked["problems"].append("IB didn't answer the preview in time. Try again.")
        except Exception as exc:
            checked["problems"].append(f"IB couldn't preview this order ({mask_secrets(exc)}).")
    return {
        "con_id": order.con_id, "symbol": contract.symbol, "exchange": contract.primaryExchange,
        "currency": contract.currency, "action": order.action, "quantity": order.quantity,
        "order_type": order.order_type, "limit_price": order.limit_price, "tif": order.tif,
        "price_used": checked["price"], "estimated_value": checked["value"],
        "estimated_value_base": checked["value_base"], "base_currency": checked["base_currency"],
        "held_quantity": checked["held"], "max_order_value": checked["status"]["max_order_value"],
        "what_if": what_if, "problems": checked["problems"], "can_submit": not checked["problems"],
        # Set when the order would borrow: {currency, amount, cost, available, reason, blocked, message}
        "borrow": checked.get("borrow"),
        "confirmation_token": token, "confirmation_expires_in_s": trading.TOKEN_LIFETIME_S if token else None,
    }

confirmation_tokens = trading.ConfirmationTokens()
order_lock = asyncio.Lock()
# Statuses that mean IB hasn't accepted or rejected the order yet (PreSubmitted = accepted, waiting
# for the market to open)
PENDING_STATUSES = {"PendingSubmit", "ApiPending"}

class PlaceOrderRequest(OrderRequest):
    confirmation_token: str

def trade_summary(trade):
    """An order's state for the app (also used by the order status stream later)."""
    status = trade.orderStatus
    messages = [entry.message for entry in trade.log if entry.message]
    # Commission is reported per fill, a moment after the fill itself
    commissions = [clean(f.commissionReport.commission) for f in trade.fills
                   if f.commissionReport and clean(f.commissionReport.commission) is not None
                   and f.commissionReport.commission < trading.UNSET]
    return {
        "order_id": trade.order.orderId, "perm_id": trade.order.permId or None,
        "con_id": trade.contract.conId, "symbol": trade.contract.symbol,
        "action": trade.order.action, "quantity": trade.order.totalQuantity, "order_type": trade.order.orderType,
        "tif": trade.order.tif or "DAY",
        "limit_price": clean(trade.order.lmtPrice) if trade.order.orderType == "LMT" else None,
        "status": status.status, "filled": status.filled, "remaining": status.remaining,
        "avg_fill_price": clean(status.avgFillPrice) or None,
        "message": messages[-1] if messages else None,
        "commission": sum(commissions) if commissions else None,
        "commission_currency": next((f.commissionReport.currency for f in trade.fills
                                     if f.commissionReport and f.commissionReport.currency), None),
    }

@router.post("/orders", dependencies=[Depends(require_ib)])
async def place_order(order: PlaceOrderRequest, request: Request):
    """Place an order that was previewed: needs the preview's confirmation token for exactly this
    order, and passes every guardrail check again (trading status, limits) right before sending."""
    check_origin(request)
    if order_lock.locked():
        raise HTTPException(status_code=409, detail="Another order is being placed")
    async with order_lock:
        details = order.model_dump(exclude={"confirmation_token"})
        problem = confirmation_tokens.redeem(order.confirmation_token, order.con_id, details, time.monotonic())
        if problem:
            raise HTTPException(status_code=409, detail=problem)
        checked = await checked_order(order)
        if checked["problems"]:
            raise HTTPException(status_code=409, detail=" ".join(checked["problems"]))
        trade = ib.placeOrder(checked["contract"], trading.build_order(details))
        print(f"Order placed: {order.action} {order.quantity:g} {checked['contract'].symbol} {order.order_type} "
              f"(order {trade.order.orderId})")
        # Give IB a moment to accept or reject it, so the app can say which
        for _ in range(25):
            if trade.orderStatus.status not in PENDING_STATUSES:
                break
            await asyncio.sleep(0.2)
        return trade_summary(trade)

# Orders IB still might fill: these can be cancelled or changed
OPEN_STATUSES = {"PendingSubmit", "ApiPending", "PreSubmitted", "Submitted"}

def open_trade(order_id):
    trade = next((t for t in ib.openTrades() if t.order.orderId == order_id), None)
    if trade is None or trade.orderStatus.status not in OPEN_STATUSES:
        raise HTTPException(status_code=404, detail="No open order with that id (it may have filled or been cancelled)")
    return trade

async def settled(trade, waiting_for):
    """Wait up to 5 s for IB to confirm a cancel or change, then describe the order."""
    for _ in range(25):
        if trade.orderStatus.status not in waiting_for:
            break
        await asyncio.sleep(0.2)
    return trade_summary(trade)

@router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_ib)])
async def cancel_order(order_id: int, request: Request):
    """Cancel an open order. No confirmation token: cancelling only reduces what can happen."""
    check_origin(request)
    trade = open_trade(order_id)
    ib.cancelOrder(trade.order)
    print(f"Order cancel requested: order {order_id} ({trade.contract.symbol})")
    return await settled(trade, OPEN_STATUSES | {"PendingCancel"})

class ModifyOrderRequest(BaseModel):
    quantity: float = Field(gt=0)
    limit_price: float | None = None
    # None keeps the order's current type / time in force
    order_type: Literal["MKT", "LMT"] | None = None
    tif: Literal["DAY", "GTC"] | None = None
    confirmation_token: str

# IBKR messages that aren't a rejection (399: "won't be placed until the market opens")
WARNING_CODES = {399}
# How long to listen for IBKR rejecting a change made in place
MODIFY_CHECK_S = 2.0
CANCELLED_STATUSES = {"Cancelled", "ApiCancelled"}

async def change_rejection(trade, log_before):
    """IBKR's reason if it refused the change just sent (e.g. error 329 "Cannot change to the new
    order type"), or None if it accepted it."""
    waited = 0.0
    while waited < MODIFY_CHECK_S:
        for entry in trade.log[log_before:]:
            if entry.errorCode and entry.errorCode not in WARNING_CODES:
                return entry.message or f"IBKR error {entry.errorCode}"
        await asyncio.sleep(0.1)
        waited += 0.1
    return None

async def cancel_and_replace(trade, details, reason):
    """When IBKR won't change an order in place: cancel it, then place the changed order as a new one."""
    if trade.orderStatus.filled:
        raise HTTPException(status_code=409, detail=(
            f"IBKR can't make this change to the order ({reason}). Part of it has already filled, so it "
            "wasn't cancelled and replaced. Cancel it and place a new order for the rest."))
    ib.cancelOrder(trade.order)
    for _ in range(25):
        if trade.orderStatus.status in CANCELLED_STATUSES:
            break
        await asyncio.sleep(0.2)
    else:
        raise HTTPException(status_code=409, detail=(
            f"IBKR can't make this change to the order ({reason}), and the original order couldn't be "
            "cancelled, so nothing was changed."))
    replacement = ib.placeOrder(trade.contract, trading.build_order(details))
    print(f"Order {trade.order.orderId} ({trade.contract.symbol}) replaced by order {replacement.order.orderId}: {reason}")
    result = await settled(replacement, {"PendingSubmit", "ApiPending"})
    result["replaced"] = {"order_id": trade.order.orderId, "reason": reason}
    return result

@router.post("/orders/{order_id}/modify", dependencies=[Depends(require_ib)])
async def modify_order(order_id: int, change: ModifyOrderRequest, request: Request):
    """Change an open order's quantity, limit price, type or time in force (the side stays). The
    changed order must be previewed first (POST /orders/preview with the new values) and its token
    passed here. The change is made in place when IBKR allows it; when IBKR refuses (e.g. market to
    limit), the order is cancelled and placed again, and the response's "replaced" says so."""
    check_origin(request)
    async with order_lock:
        trade = open_trade(order_id)
        if trade.order.orderType not in trading.ORDER_TYPES:
            raise HTTPException(status_code=409, detail="Only market and limit orders placed here can be changed.")
        order_type = change.order_type or trade.order.orderType
        details = {
            "con_id": trade.contract.conId, "action": trade.order.action, "quantity": change.quantity,
            "order_type": order_type, "limit_price": change.limit_price if order_type == "LMT" else None,
            "tif": change.tif or trade.order.tif or "DAY",
        }
        problem = confirmation_tokens.redeem(change.confirmation_token, details["con_id"], details, time.monotonic())
        if problem:
            raise HTTPException(status_code=409, detail=problem)
        checked = await checked_order(OrderRequest(**details), replacing_order_id=order_id)
        if checked["problems"]:
            raise HTTPException(status_code=409, detail=" ".join(checked["problems"]))

        original = {field: getattr(trade.order, field) for field in ("totalQuantity", "orderType", "lmtPrice", "tif")}
        trade.order.totalQuantity = change.quantity
        trade.order.orderType = order_type
        trade.order.lmtPrice = round(change.limit_price, 4) if order_type == "LMT" else 0.0
        trade.order.tif = details["tif"]
        log_before = len(trade.log)
        ib.placeOrder(trade.contract, trade.order)  # same order id = a change, not a new order
        print(f"Order change requested: order {order_id} ({trade.contract.symbol}) to {change.quantity:g} {order_type} {details['tif']}")
        reason = await change_rejection(trade, log_before)
        if reason is None:
            return await settled(trade, {"PendingSubmit", "ApiPending"})
        # IBKR kept the order as it was: put our copy back before deciding what to do
        for field, value in original.items():
            setattr(trade.order, field, value)
        return await cancel_and_replace(trade, details, reason)

ORDER_LISTS = {"open": "your open orders", "completed": "today's completed orders", "executions": "today's executions"}

async def ib_list(what, request):
    """One of IBKR's order lists, or a 502 that says which one failed (a plain 500 would reach the
    page without CORS headers, so it could only say "Failed to fetch")."""
    try:
        return await asyncio.wait_for(request, timeout=10)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=502, detail=f"IBKR didn't send {ORDER_LISTS[what]} in time. Try again.")
    except ConnectionError:
        raise  # Gateway dropped: the app-wide handler answers 503
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"IBKR couldn't send {ORDER_LISTS[what]} ({mask_secrets(exc)}).")

def order_names(infos):
    """{con_id: company name} from get_contract_info results ((contract, long_name) pairs)."""
    return {contract.conId: display_name(long_name, contract.symbol)[0]
            for contract, long_name in infos if contract is not None and long_name}

@router.get("/orders", dependencies=[Depends(require_ib)])
async def orders():
    """Open orders (from every client, including TWS and mobile), and today's filled and cancelled
    orders, for the Orders page."""
    open_trades, completed, fills = await asyncio.gather(
        ib_list("open", ib.reqAllOpenOrdersAsync()),
        ib_list("completed", ib.reqCompletedOrdersAsync(apiOnly=False)),
        ib_list("executions", ib.reqExecutionsAsync()),
    )
    con_ids = sorted({t.contract.conId for t in [*open_trades, *completed]})
    names = order_names(await asyncio.gather(*(get_contract_info(con_id) for con_id in con_ids)))
    try:
        return trading.orders_overview(open_trades, completed, fills, names)
    except Exception as exc:
        print(f"Orders overview failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
        raise HTTPException(status_code=502, detail=f"Couldn't read the orders from IBKR ({exc.__class__.__name__}).")

# ---------- order status stream ----------

# One queue per open stream; IB's order events are copied into every queue
order_listeners = set()
STREAM_HEARTBEAT_S = 15

def publish_trade(trade, *_):
    """Called by ib_async for every order status change and fill."""
    if not order_listeners:
        return
    update = trade_summary(trade)
    for queue in list(order_listeners):
        queue.put_nowait(update)

ib.orderStatusEvent += publish_trade
ib.execDetailsEvent += publish_trade

@router.get("/orders/stream", dependencies=[Depends(require_ib)])
async def order_stream(request: Request):
    """Server-Sent Events: "orders" (every order this connection knows, at the start), then "order"
    whenever one is submitted, filled or cancelled. A comment every 15 s keeps the connection open."""
    queue = asyncio.Queue()
    order_listeners.add(queue)

    async def events():
        try:
            yield sse("orders", [trade_summary(t) for t in ib.trades()])
            # Ends when the page goes away or the server is stopping (see web.stopping)
            while not web.stopping.is_set() and not await request.is_disconnected():
                update = await next_or_none(queue, STREAM_HEARTBEAT_S)
                if web.stopping.is_set():
                    break
                yield sse("order", update) if update is not None else ": still here\n\n"
        finally:
            order_listeners.discard(queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
