# Paper trading test run (Milestone 6, issue #33)

A checklist for testing every order flow end to end on the **paper** account before Milestone 6
is called done. Run it in development (the Mac app is always read only).

## Before you start

1. Log IB Gateway in to the **paper** account (port 4002). Check the toolbar badge says
   **Paper account**. If it says Live account, stop.
2. In `.env`: `TRADING_MODE=paper` and, for the limit test, `MAX_ORDER_VALUE=10000`.
3. Restart the backend (the connection is only opened without read only at start), then check
   `GET /trading/status` says `"can_trade": true`.
4. Pick a cheap, liquid stock during market hours (e.g. an ASX 200 stock in the morning, or a
   US large cap at night).

## Flows

| # | Do this | Expect |
|---|---|---|
| 1 | Markets → search a stock → **Buy** → limit order 1 share well **below** the price → Review Order | Estimates show IBKR's commission; review sheet shows the limit callout |
| 2 | **Place Buy Order** | Result sheet "Order placed"; Orders → Open lists it as Working |
| 3 | Orders → **Modify** → change the quantity to 2 → Review → **Change Order** | Order now shows 2 shares; still Working |
| 4 | Orders → **Cancel** | Moves to the Cancelled tab |
| 5 | Buy 1 share with a **market** order | Result sheet goes to "Order filled" with the average price and total incl. commission; Positions shows the holding after Done |
| 6 | Positions → that holding → **Sell** 1 share (market) | Fills; holding disappears or drops by 1 |
| 7 | Sell more shares than you hold | Ticket lists "You can sell at most …"; Review Order disabled |
| 8 | Buy an order worth more than `MAX_ORDER_VALUE` | Ticket lists the limit problem; Review Order disabled |
| 9 | Open the ticket, wait over 2 minutes on the review sheet, then Place | Error: the confirmation expired; Edit → Review again works |
| 10 | Double-click **Place Buy Order** | Only one order is placed |
| 11 | Set `TRADING_MODE=off`, restart | Buy/Sell/Modify/Cancel are disabled with "Trading is off" |

## After the run

- Note anything that behaved differently in issue #33, with the order ids from the Orders page.
- Set `TRADING_MODE` back to `off` if you don't want trading on day to day.
