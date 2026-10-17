# Purchase dates from IBKR (Flex Query)

Interactive Brokers' trading API (the one IB Gateway provides) doesn't say when you bought a
holding, so the app can't work out the 12-month date for the capital gains tax (CGT) discount.
IBKR's **Flex Web Service** can: it sends a report of your open positions, lot by lot, with the
date each lot was bought, plus your recent trades. The app downloads that report with a token you
create once.

The token only lets someone download reports for your account (it can't trade), but treat it like
a password: the app never saves it to disk, and you can revoke it in Client Portal at any time.

IBKR occasionally renames menu items; if a name below doesn't match exactly, look for the closest one.

## 1. Create the Flex Query

1. Log in to **Client Portal** and open **Performance & Reports → Flex Queries**.
2. Next to **Activity Flex Query**, click **+** (create).
3. Name it, for example `Portfolio Manager lots`.
4. Add these sections:
   - **Open Positions**: choose **Lot** as the level of detail, and select all fields (at least
     Symbol, Conid, Currency, Asset Class, Quantity, Cost Basis Price and Open Date Time).
   - **Trades**: choose **Execution**, and select all fields (at least Symbol, Conid, Currency,
     Asset Class, Trade Date, Buy/Sell, Quantity and Trade Price).
5. Delivery settings:
   - **Format**: XML
   - **Period**: Last 365 Calendar Days
   - **Date format**: yyyyMMdd, **Time format**: HHmmss, **Date/time separator**: `;` (semicolon)
6. Save. The query appears in the list with a **Query ID** (a number). Note it down.

Open Positions at lot level is what gives the purchase dates, however long ago you bought. The
Trades section only covers the report period (up to a year); the app uses it as a fallback.

## 2. Create a Flex Web Service token

1. On the same **Flex Queries** page, open **Flex Web Service Configuration** (the gear icon).
2. Turn the Flex Web Service on and click **Generate New Token**. Choose how long it stays valid
   (up to a year); you'll need a new one when it expires.
3. Copy the token.

## 3. Give them to the app

- **Development** (running the backend yourself): add both to `.env` in the project root:
  ```
  IB_FLEX_TOKEN=your token
  IB_FLEX_QUERY_ID=your query ID
  ```
- **Mac app**: entered in Settings (not available yet: the Settings rows are waiting for a design).
  Like the Anthropic key, the token will be kept in memory only and entered again after restarting.
