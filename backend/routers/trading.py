"""Trading (Milestone 6): status, preview, place, change and cancel orders, the orders list and
the order status stream."""
import asyncio
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import trading
from ib_core import build_quote, clean, fetch_tickers, get_contract_info, ib, require_ib
from names import display_name
from secrets_guard import mask_secrets
from web import check_origin, sse
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

async def checked_order(order: OrderRequest):
    """Everything an order needs before IB sees it: the contract, the price it's valued at, the
    guardrail status and the problems that stop it (trading.check_order)."""
    contract, _ = await get_contract_info(order.con_id)
    if contract is None or contract.secType != "STK":
        raise HTTPException(status_code=404, detail="Unknown stock")
    if order.order_type == "LMT" and order.limit_price:
        price = order.limit_price
    else:
        tickers = await fetch_tickers([contract])
        price = (await build_quote(order.con_id, tickers.get(order.con_id)))["last"]
    account_data = await account()
    base = account_data["currency"]
    fx_rate = 1 if contract.currency == base else account_data["fx_rates"].get(contract.currency)
    held = next((item.position for item in ib.portfolio() if item.contract.conId == order.con_id), 0)
    status = trading.status(ib.managedAccounts())
    problems, value, value_base = trading.check_order(order.model_dump(), price, fx_rate, held, status)
    return {
        "contract": contract, "price": price, "held": held, "status": status, "problems": problems,
        "value": value, "value_base": value_base, "base_currency": base,
    }

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
        "order_type": order.order_type, "limit_price": order.limit_price,
        "price_used": checked["price"], "estimated_value": checked["value"],
        "estimated_value_base": checked["value_base"], "base_currency": checked["base_currency"],
        "held_quantity": checked["held"], "max_order_value": checked["status"]["max_order_value"],
        "what_if": what_if, "problems": checked["problems"], "can_submit": not checked["problems"],
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
    confirmation_token: str

@router.post("/orders/{order_id}/modify", dependencies=[Depends(require_ib)])
async def modify_order(order_id: int, change: ModifyOrderRequest, request: Request):
    """Change an open order's quantity or limit price. The changed order must be previewed first
    (POST /orders/preview with the new numbers) and its token passed here; side and type stay."""
    check_origin(request)
    async with order_lock:
        trade = open_trade(order_id)
        details = {
            "con_id": trade.contract.conId, "action": trade.order.action, "quantity": change.quantity,
            "order_type": trade.order.orderType, "limit_price": change.limit_price if trade.order.orderType == "LMT" else None,
        }
        if details["order_type"] not in trading.ORDER_TYPES:
            raise HTTPException(status_code=409, detail="Only market and limit orders placed here can be changed.")
        problem = confirmation_tokens.redeem(change.confirmation_token, details["con_id"], details, time.monotonic())
        if problem:
            raise HTTPException(status_code=409, detail=problem)
        checked = await checked_order(OrderRequest(**details))
        if checked["problems"]:
            raise HTTPException(status_code=409, detail=" ".join(checked["problems"]))
        trade.order.totalQuantity = change.quantity
        if details["order_type"] == "LMT":
            trade.order.lmtPrice = round(change.limit_price, 4)
        ib.placeOrder(trade.contract, trade.order)  # same order id = a change, not a new order
        print(f"Order change requested: order {order_id} ({trade.contract.symbol}) to {change.quantity:g}")
        return await settled(trade, {"PendingSubmit", "ApiPending"})

@router.get("/orders", dependencies=[Depends(require_ib)])
async def orders():
    """Open orders (from every client, including TWS and mobile), and today's filled and cancelled
    orders, for the Orders page."""
    open_trades, completed, fills = await asyncio.gather(
        asyncio.wait_for(ib.reqAllOpenOrdersAsync(), timeout=10),
        asyncio.wait_for(ib.reqCompletedOrdersAsync(apiOnly=False), timeout=10),
        asyncio.wait_for(ib.reqExecutionsAsync(), timeout=10),
    )
    con_ids = {t.contract.conId for t in [*open_trades, *completed]}
    infos = await asyncio.gather(*(get_contract_info(con_id) for con_id in con_ids))
    names = {con_id: display_name(long_name, None)[0] for con_id, (_, long_name) in zip(con_ids, infos) if long_name}
    return trading.orders_overview(open_trades, completed, fills, names)

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
            while not await request.is_disconnected():
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=STREAM_HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": still here\n\n"
                    continue
                yield sse("order", update)
        finally:
            order_listeners.discard(queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
