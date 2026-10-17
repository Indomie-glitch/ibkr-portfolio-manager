# Paper trading test run (Milestone 6, issue #33)

A checklist for testing every order flow end to end on a **paper** account before using a live
one. Trading is on whenever the app is connected, in the browser version and the Mac app, so the
only thing that keeps this test on paper money is logging in to the paper account.

## Before you start

1. Log IB Gateway (or the Mac app) in to the **paper** account. Check the toolbar badge says
   **Paper account** (blue). If it says **Live account** (red), stop and sign in to paper instead.
2. For the limit test, set `MAX_ORDER_VALUE=10000` in `.env` (the default) and restart the backend.
3. Pick a cheap, liquid stock during market hours (e.g. an ASX 200 stock in the morning, or a
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
| 11 | Repeat 1–2 in the **Mac app** | Same results (its Gateway now allows API orders) |
| 12 | Quit IB Gateway | Buy/Sell/Modify/Cancel are disabled with "Trading is unavailable until IB Gateway is connected" |

## After the run

Note anything that behaved differently in issue #33, with the order ids from the Orders page.
