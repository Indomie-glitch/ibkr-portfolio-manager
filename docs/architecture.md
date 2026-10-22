# Architecture

How the IBKR Portfolio Manager fits together, from the big picture down to single actions. Each diagram zooms in one level, like a map going from country to city to street.

1. [The big picture](#1-the-big-picture): the app and everything outside it
2. [Inside the app](#2-inside-the-app): the parts that run on your Mac
3. [Inside the backend](#3-inside-the-backend): Python modules
4. [Inside the frontend](#4-inside-the-frontend): React pages and components
5. [Key flows](#5-key-flows): step by step sequences for the main actions
6. [Where data lives](#6-where-data-lives)

GitHub draws these diagrams automatically. To edit one by hand in draw.io, use Arrange → Insert → Advanced → Mermaid and paste the diagram's code.

> Keep this file current: when a change adds, removes or renames a module, page, endpoint or external service, update the matching diagram in the same PR.

---

## 1. The big picture

Who uses the app, and which outside services it talks to.

```mermaid
flowchart LR
    user(["You<br/>(or a friend)"])

    subgraph mac["Your Mac"]
        app["Portfolio Manager<br/>(Mac app or browser dev version)"]
        gw["IB Gateway<br/>IBKR's own program,<br/>holds the broker login"]
    end

    ibkr[("IBKR servers<br/>accounts, prices, orders")]
    flex[("IBKR Flex Web Service<br/>purchase history report")]
    yahoo[("Yahoo Finance<br/>key stats, news,<br/>company info")]
    claude[("Anthropic API<br/>Claude writes the<br/>AI summaries and<br/>judges news sentiment")]
    gh[("GitHub Releases<br/>new app versions")]

    user -->|clicks, types| app
    app -->|"positions, quotes,<br/>orders (API on a local port)"| gw
    gw <-->|"encrypted session<br/>(username + password once)"| ibkr
    app -->|"daily report<br/>(Flex token)"| flex
    app -->|"public data<br/>(yfinance)"| yahoo
    app -->|"facts sheet or headlines in,<br/>summary or sentiment out (API key)"| claude
    app -->|"check for update,<br/>download signed update"| gh
```

**How to read it:** the app never talks to IBKR's servers directly. Everything to do with your account goes through IB Gateway, a program from IBKR that runs next to the app and keeps the logged in session. Yahoo fills in data IBKR doesn't provide, Claude only explains numbers the app has already calculated, and GitHub is only used for updates.

---

## 2. Inside the app

The separate programs running on your Mac, and how they connect. There are two ways to run it.

### Mac app (what friends install)

```mermaid
flowchart TB
    subgraph bundle["Portfolio Manager.app"]
        direction TB
        shell["Tauri shell (Rust)<br/>src-tauri/src/<br/>window, menus, sign in,<br/>settings, updates,<br/>links to the browser"]
        ui["React frontend<br/>frontend/src/<br/>everything you see"]
        be["Python backend<br/>backend/ (packed by PyInstaller)<br/>FastAPI on a random free port"]
        ibc["IBC + StdinLauncher (Java)<br/>starts Gateway and types<br/>the login for you"]
    end

    gw["IB Gateway<br/>(installed separately,<br/>port 4012)"]
    disk[("Application Support/<br/>settings.json, lots.sqlite,<br/>summaries.sqlite, news_sentiment.sqlite,<br/>usage.sqlite, risk_prices.sqlite, gateway/")]

    shell -->|"opens window, injects<br/>backend URL + token"| ui
    ui -->|"Tauri commands<br/>(sign_in, set_api_key, ...)"| shell
    ui -->|"HTTP + X-App-Token header"| be
    shell -->|"starts it, sends token,<br/>API key and settings over stdin"| be
    shell -->|"starts it, sends username<br/>and password over stdin"| ibc
    ibc -->|launches + logs in| gw
    be -->|"ib_async, client ID 17"| gw
    shell --- disk
    be --- disk
```

### Browser dev version (what you run while building)

```mermaid
flowchart LR
    browser["Browser<br/>localhost:5173<br/>(npm run dev)"] -->|HTTP, no token| be["Python backend<br/>localhost:8000<br/>(uvicorn --reload)"]
    be -->|"ib_async, client ID 1"| gw["IB Gateway<br/>port 4002<br/>(you log in yourself)"]
    env[(".env<br/>API key, Flex token,<br/>IB port, AI model")] -.-> be
```

**How to read it:** in the Mac app, the Rust shell is the boss. It starts the backend and Gateway, passes secrets to them through stdin (a private pipe between two programs, so the secrets are never written to a file), and kills both when you quit. The frontend only ever talks to the backend over HTTP, plus a few direct commands to the Rust shell for things like signing in. In the dev version you start each piece yourself, and settings come from `.env` instead.

**Why the token:** the backend listens on a local port, so other programs on your Mac could call it. The random per-launch token means only the app's own window is accepted.

---

## 3. Inside the backend

`main.py` only creates the app. Each file in `routers/` handles one area of the API (the URLs the frontend calls), and the modules below them do the real work.

```mermaid
flowchart TB
    main["main.py<br/>creates the app, starts<br/>background tasks"]

    subgraph routers["routers/ (the API)"]
        r_app["app.py<br/>/health"]
        r_pos["positions.py<br/>/positions /account /quotes<br/>/search /prices /history<br/>/profile /stats /news /performance"]
        r_flex["flex.py<br/>/lots/status /lots/{id}"]
        r_sum["summaries.py<br/>/summary/... /portfolio-summary/...<br/>/usage"]
        r_trade["trading.py<br/>/trading/status /orders<br/>/orders/preview /stream<br/>cancel, modify"]
        r_risk["risk.py<br/>/risk /risk/bankruptcy"]
    end

    subgraph core["Shared"]
        ib_core["ib_core.py<br/>IB connection, contract<br/>info, quotes, price bars"]
        ib_conn["ib_connection.py<br/>connect + reconnect,<br/>client ID clashes"]
        web["web.py<br/>Origin check, SSE streams"]
        cache["cache.py<br/>in-memory cache"]
        cfg["config.py<br/>.env + app settings"]
        guard["secrets_guard.py<br/>masks secrets in errors"]
        names["names.py<br/>tidy company names"]
        fx["fx.py<br/>exchange rates: ledger,<br/>IB forex, Yahoo;<br/>daily rate pairs"]
    end

    subgraph data["Data and AI"]
        yahoo["yahoo.py<br/>yfinance wrapper"]
        trading["trading.py<br/>guardrails, confirmation<br/>tokens, order summaries"]
        lots["lots.py<br/>purchase lots, CGT dates,<br/>daily refresh"]
        flex["flex_report.py<br/>download + parse Flex XML"]
        sfacts["summary_facts.py<br/>stock facts sheet<br/>(every number calculated here)"]
        pfacts["portfolio_facts.py<br/>portfolio facts sheet"]
        ai["ai_summary.py<br/>stock prompt, calls Claude,<br/>streams + checks sections"]
        pai["portfolio_summary.py<br/>portfolio prompt + checks"]
        store["summary_store.py<br/>saved summaries (SQLite)"]
        senti["news_sentiment.py<br/>news good/bad + strength,<br/>saved per article (SQLite)"]
        usage["usage_store.py<br/>tokens + cost of every<br/>Claude call (SQLite)"]
        rdata["risk_data.py<br/>daily closes (SQLite),<br/>base currency returns<br/>per window"]
        rmath["risk.py<br/>risk maths (numpy, pure)"]
        rsec["risk_sections.py<br/>one function per<br/>Risk page section"]
    end

    main --> routers
    main -->|"keep_connected task"| ib_core
    main -->|"keep_refreshed task"| lots
    ib_core --> ib_conn

    r_pos --> ib_core & yahoo & cache & names & senti & fx
    r_trade -.-> fx
    r_risk -.-> fx
    rdata -.->|rate pairs| fx
    fx --> ib_core & yahoo & cache
    r_flex --> lots & ib_core
    r_trade --> trading & ib_core & web
    r_sum --> sfacts & pfacts & ai & pai & store & lots & web & usage
    r_sum -.->|reuses| r_pos
    r_risk --> rdata & rsec & cache & ib_core
    rsec --> rmath
    r_risk -.->|reuses| r_pos
    r_sum -.->|D:risk| r_risk
    rdata --> yahoo & rmath

    lots --> flex
    sfacts --> yahoo
    pfacts --> sfacts
    pai --> ai

    ib_core -->|ib_async| GW[["IB Gateway"]]
    yahoo -->|yfinance| YF[["Yahoo Finance"]]
    flex -->|HTTPS| FX[["Flex Web Service"]]
    ai -->|anthropic SDK| AN[["Anthropic API"]]
    senti -->|anthropic SDK| AN
    senti --> usage
```

**How to read it:** arrows point from the file that uses something to the file it uses. The important rule in the AI part: `summary_facts.py` and `portfolio_facts.py` calculate every number, and Claude (via `ai_summary.py`) is only allowed to explain them and must cite which fact each point comes from. That is how the summaries avoid made up numbers.

**Background tasks** (started by `main.py` when the server starts):
* `keep_connected`: keeps trying to connect to IB Gateway every 5 seconds, so the backend starts fine even when Gateway isn't running and reconnects after drops.
* `keep_refreshed`: downloads the Flex purchase report once a day.

---

## 4. Inside the frontend

`App.jsx` holds the shared data (account, positions, quotes, connection state) and shows one page at a time.

```mermaid
flowchart TB
    main["main.jsx"] --> App["App.jsx<br/>loads account, positions, quotes,<br/>trading status; picks the page"]

    Sidebar --> SidebarWatchlists["SidebarWatchlists.jsx<br/>+ button, rows with counts,<br/>naming, Rename / Delete,<br/>drop stock rows here"]
    App --> Sidebar & Toolbar & SessionBanner & UpdatePrompt & ConnectionMessage
    App --> Setup["pages/setup/<br/>first run + sign in (Mac app):<br/>Setup.jsx flow, one file per screen"]
    App --> Overview["pages/Overview.jsx"]
    App --> Positions["pages/Positions.jsx"]
    App --> Markets["pages/Markets.jsx"]
    App --> Orders["pages/Orders.jsx"]
    App --> Watchlist["pages/Watchlist.jsx<br/>one watchlist: its stocks,<br/>add from search, empty state"]
    App --> Risk["pages/Risk.jsx<br/>command bar, headline tiles,<br/>12 panels, data notes"]
    Risk --> RiskTile["risk/RiskTile.jsx"] & RiskPanel["risk/RiskPanel.jsx<br/>frame: RSK tag, title, ⓘ;<br/>loads its own section"]
    RiskTile & RiskPanel --> InfoButton["risk/InfoButton.jsx<br/>ⓘ + explainer popover"]
    App --> Settings["SettingsSheet.jsx + pages/Settings.jsx<br/>(opened from the account menu)"]
    App --> Ticket["OrderTicket.jsx<br/>buy/sell form, live preview"] --> Confirm["OrderConfirm.jsx<br/>review sheet, then 'Order filled'"]

    Overview --> StatCard & PositionsTable & AllocationCard & PortfolioSummaryCard["PortfolioSummaryCard.jsx<br/>AI portfolio summary"]
    PortfolioSummaryCard & detail --> SummaryPanel["detail/SummaryPanel.jsx<br/>AI summary panel shared by<br/>stocks and the portfolio"]
    Positions --> HoldingsList & HoldingDetail
    Markets --> HoldingDetail
    Watchlist --> HoldingDetail
    Markets & Watchlist --> StockRow["StockRow.jsx"]
    Markets & Watchlist & Positions --> MarketFilter["MarketFilter.jsx<br/>All / ASX / US"]
    HoldingDetail --> WatchButton["WatchButton.jsx<br/>Watch menu (PopupMenu)"]

    HoldingDetail["HoldingDetail.jsx<br/>price, chart, your position<br/>(incl. purchase and CGT dates)"] --> PriceChart
    HoldingDetail --> detail["components/detail/<br/>KeyStats, About, News<br/>(with sentiment arrows),<br/>Performance, AI summary<br/>(collapsible sections)"]

    subgraph lib["lib/ + hooks/"]
        api["lib/api.js<br/>every backend call"]
        helpers["lib/format.js, holdings.js,<br/>summaryDiff.js, summarySections.js,<br/>lotCards.js, listPanes.js,<br/>watchlists.js (localStorage store),<br/>orderTicket.js (ticket maths)"]
        riskhelpers["lib/riskData.js (one GET /risk<br/>shared by every panel),<br/>riskLayout.js, riskFormat.js,<br/>riskExplainers.js (ⓘ copy)"]
        hooks["hooks/useFetch, useLogin,<br/>useResizableWidth, useStockDrop,<br/>usePrices, useStockSearch,<br/>useMenu, appearance"]
    end

    subgraph desktop["desktop/ (Mac app only)"]
        tauri["appSession, appGateway,<br/>appApiKey, appSettings,<br/>appUpdater, appWindow"]
    end

    App & Markets & Watchlist & Orders & HoldingDetail & Ticket & Confirm & Settings --> api
    RiskTile & RiskPanel & Risk --> riskhelpers --> api
    api -->|"HTTP / streams"| BE[["Python backend"]]
    Setup & Settings & UpdatePrompt --> tauri
    tauri -->|Tauri commands| RS[["Rust shell"]]
```

**How to read it:** pages are the screens in the sidebar; components are the pieces inside them. Every call to the backend goes through `lib/api.js`, so that is the one file to read to see what the frontend asks for. The `desktop/` files only do anything in the Mac app; in the browser they are switched off.

---

## 5. Key flows

Sequence diagrams: read top to bottom. Each arrow is one program asking another for something.

### 5.1 Opening the Mac app and signing in

```mermaid
sequenceDiagram
    actor You
    participant Rust as Tauri shell (Rust)
    participant UI as React frontend
    participant BE as Python backend
    participant IBC as IBC + Gateway
    participant IBKR as IBKR servers

    You->>Rust: open the app
    Rust->>BE: start backend on a free port, send token (stdin)
    Rust->>UI: open window with backend URL + token
    UI->>BE: GET /health (until it answers)
    BE-->>UI: connected: false
    UI->>You: sign in screen (pages/setup/SignInForm.jsx)
    You->>UI: username, password, Paper/Live
    UI->>Rust: sign_in command
    Rust->>IBC: start Gateway, send login (stdin)
    IBC->>IBKR: log in
    IBKR-->>You: approve on IBKR Mobile (live accounts)
    IBKR-->>IBC: logged in
    loop every 5 s (keep_connected)
        BE->>IBC: connect (ib_async)
    end
    IBC-->>BE: connected
    UI->>BE: GET /health
    BE-->>UI: connected: true
    UI->>BE: /account, /positions, /quotes
    UI->>You: Overview
```

### 5.2 Loading a page (e.g. Positions)

```mermaid
sequenceDiagram
    participant UI as React (api.js)
    participant R as routers/positions.py
    participant C as cache.py
    participant IB as ib_core.py → Gateway
    participant Y as yahoo.py → Yahoo

    UI->>R: GET /positions
    R->>IB: ib.portfolio() + contract names
    IB-->>R: holdings
    R-->>UI: JSON list
    UI->>R: GET /history/{id}?range=1M
    R->>C: cached for 60 s?
    alt cached
        C-->>R: bars
    else not cached
        R->>IB: reqHistoricalData
        IB-->>R: bars
    end
    R-->>UI: bars → PriceChart
    UI->>R: GET /stats/{id}, /news/{id} (only open sections)
    R->>Y: yfinance (one call at a time)
    Y-->>R: data (or 502 → that section shows "unavailable")
    R-->>UI: JSON
```

### 5.3 Generating an AI stock summary

```mermaid
sequenceDiagram
    actor You
    participant UI as AiSummarySection
    participant R as routers/summaries.py
    participant F as summary_facts.py
    participant AI as ai_summary.py
    participant Claude as Anthropic API
    participant S as summary_store.py

    You->>UI: Generate
    UI->>R: POST /summary/{id} (stream)
    R->>F: build facts sheet
    F->>F: price, valuation, events, news,<br/>your position + lots (holdings only),<br/>change since last
    F-->>R: facts with ids (D:..., N1...)
    R-->>UI: event: facts
    R->>AI: facts + 10 section prompt<br/>(9, without Your position, for a stock<br/>you don't own, e.g. from Markets)
    AI->>Claude: request (structured output)
    loop each section as it finishes
        Claude-->>AI: partial JSON
        AI->>AI: check citations, flag advice wording
        AI-->>R: section
        R-->>UI: event: section (appears on screen)
    end
    R->>S: save summary (keep last 20)
    R-->>UI: event: done
```

The portfolio summary works the same way, using `portfolio_facts.py` and `portfolio_summary.py` with 8 sections.

### 5.4 Placing an order

```mermaid
sequenceDiagram
    actor You
    participant T as OrderTicket
    participant C as OrderConfirm
    participant R as routers/trading.py
    participant G as trading.py (guardrails)
    participant IB as Gateway

    You->>T: Buy, quantity, price
    T->>R: POST /orders/preview (500 ms after typing stops)
    R->>G: check: whole shares, value ≤ MAX_ORDER_VALUE,<br/>no short selling, connected
    R->>IB: what-if order (nothing is sent)
    IB-->>R: cost, commission, margin
    R->>G: issue single use token<br/>(120 s, these exact numbers)
    R-->>T: preview + token
    You->>T: Review Order
    T->>C: preview + token
    You->>C: Place
    C->>R: POST /orders + token
    R->>G: redeem token, re-check guardrails
    R->>IB: placeOrder
    C->>R: GET /orders/stream
    loop until filled / cancelled
        IB-->>R: status update
        R-->>C: event: order
    end
    C->>You: "Order filled"
```

**Why the token:** it ties "Place" to the exact preview you saw. A double click, an old preview or changed numbers all fail, because each token works once, for 2 minutes, for one set of numbers.

### 5.5 Auto update

```mermaid
sequenceDiagram
    actor You
    participant Rust as Tauri shell (updater.rs)
    participant UI as UpdatePrompt
    participant GH as GitHub Releases
    participant BE as Backend + Gateway

    Rust->>GH: latest.json (3 s after launch, or menu "Check for Updates…")
    GH-->>Rust: version 0.2.1 available
    Rust->>UI: show prompt + release notes
    You->>UI: Update Now
    Rust->>GH: download .app.tar.gz + .sig
    Rust->>Rust: check signature against built in public key
    Rust->>BE: shutdown_for_update (Gateway, then backend)
    Rust->>Rust: replace app
    Rust->>You: restart into new version
```

### 5.6 Daily purchase history refresh

```mermaid
sequenceDiagram
    participant L as lots.py (keep_refreshed)
    participant F as flex_report.py
    participant Flex as Flex Web Service
    participant DB as lots.sqlite

    loop every 3 h
        L->>L: last success over a day old?
        L->>F: fetch report
        F->>Flex: SendRequest (token, query id)
        loop while "in progress"
            F->>Flex: GetStatement
        end
        Flex-->>F: XML
        F-->>L: lots + trades
        L->>DB: replace stored lots and trades
    end
```

When a stock is opened, `lots_for()` matches these lots to the shares you hold now and works out each lot's CGT discount date (the day after the first anniversary of purchase). The **Purchase date** and **12-month CGT date** cards in Your position fetch them with `GET /lots/{con_id}` (and `GET /lots/status`, to suggest setting up Flex when it isn't), and `lib/lotCards.js` turns them into what the cards say: one purchase, several purchases (lots bought the same day count as one), the next date still to come with the days left, or Unknown.

---

## 6. Where data lives

| Data | Where | Kept |
|---|---|---|
| Account, positions, prices, orders | IBKR, read live through Gateway | never stored by the app |
| Price history, quotes, Yahoo data | backend memory (`cache.py`) | seconds to a day, lost on quit |
| Purchase lots and trades | `lots.sqlite` | refreshed daily |
| Saved AI summaries | `summaries.sqlite` | last 20 per stock, last 20 portfolio |
| News sentiment per article | `news_sentiment.sqlite` | 90 days |
| Claude API usage: tokens and estimated cost per call | `usage.sqlite` | kept (`GET /usage` totals a month) |
| Daily closes for the risk analysis (holdings, indexes, exchange rate pairs against the account's currency) | `risk_prices.sqlite` | about 3 years, updated once a day per symbol |
| Returns over past crashes (2008, 2020, 2022) for the stress tests | `risk_prices.sqlite` (table `risk_scenarios`) | kept (fetched once per symbol) |
| App settings (Gateway port, AI model, username) | `settings.json` | until changed |
| Anthropic API key, Flex token | backend memory only (Mac app) or `.env` (dev) | until the app quits |
| IBKR password | sent to Gateway once, never stored | not kept |
| UI preferences (theme, open sections, recent stocks) | browser localStorage | until cleared |
| Watchlists (names and stocks) | browser localStorage (`watchlists`) | until deleted |

In the Mac app the files live in `~/Library/Application Support/` under the app's id; in dev they live in `data/` at the top of the repo.
