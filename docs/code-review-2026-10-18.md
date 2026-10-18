# Code review, 18 Oct 2026

A review of the whole repository (backend, frontend, Mac app shell and docs) during a code freeze. Nothing was changed: this file only lists findings so they can be picked and fixed later.

**How it was checked:** every statement in CLAUDE.md compared with the code; scripts that look for unused exports, CSS classes and backend functions; `pyflakes`; `npm audit`, `npm outdated` and `pip-audit`; a search of tracked files and git history for secrets; reading the larger files.

**Sizes:** S = under an hour, M = an afternoon, L = more than a day. IDs (D1, X2, …) are for referring to findings in issues.

## Top 10

| # | Finding | ID | Size |
|---|---|---|---|
| 1 | Trading safety docs are wrong: new orders can be "Good till cancelled", and changing an order can switch its type and time in force | D1 | S |
| 2 | "Set up Flex in Settings" points to settings that don't exist; the Mac app can't receive a Flex token at all | E1 | S (hint) / M (rows) |
| 3 | After pressing Place, a network error or a dropped update stream leaves you unsure whether the order went through | E2 | M |
| 4 | The order ticket's maths (amount → shares, totals, buying power, input parsing) has no tests | T1 | M |
| 5 | News and company website links probably don't open in the Mac app | E3 | S to verify, M to fix |
| 6 | Error messages and retries: "port 8000" shown in the Mac app, no request timeouts, failed sections never retry | E4 | M |
| 7 | CLAUDE.md is out of date in about 15 places (milestones, "No auto-updater", "GET-only", a command that doesn't exist, …) | D2 | M |
| 8 | Risky backend logic has no tests: "why the price moved", summary compare, news headline filter, secret masking, client ID fallback | T2 | M |
| 9 | `npm audit`: one high-severity issue (build tools only) and a few minor updates | S1 | S |
| 10 | The same logic in several places: Markets and Watchlist pages, three menu components, two summary streaming routes | X1–X4 | M |

---

## 1. Docs that are out of date

### D1. Trading safety docs describe old order rules (S)
- **Where:** README "Trading safety" ("Day orders in regular hours. New orders are day orders"); CLAUDE.md line 33 ("ib.placeOrder (day order, RTH only)" and "Modify opens OrderTicket with existing= (side, type and TIF locked)"); the comment above `OrderTicket` in `frontend/src/components/OrderTicket.jsx:64` ("side and type stay").
- **Reality:** the ticket has a Time in force menu (Day / Good till cancelled) for new orders (`OrderTicket.jsx:294`), `trading.build_order` sets the order's time in force from the request (`trading.py:88`), and when changing an order both Order type and Time in force can be edited (only the side is fixed). `docs/paper-trading-test.md` already tests GTC (step 1b).
- **Why it matters:** this is the safety section people read before trading a live account. A GTC order stays open after today's close, which the docs say can't happen.
- **Fix:** README: "New orders are day orders unless you choose Good till cancelled; orders never trade outside regular hours." Update CLAUDE.md line 33 and the component comment.

### D2. CLAUDE.md statements that no longer match the code (M)
Each line below was checked against the code.

| CLAUDE.md says | Actually |
|---|---|
| "Packaging (#43): … No auto-updater." (l.23) | The updater exists (#48, next line). Delete "No auto-updater". |
| "…dmg/Portfolio Manager_0.1.0_aarch64.dmg" (l.23) | Version is 0.2.0 (`frontend/package.json`); say `<version>`. |
| "The backend API stays GET-only." (l.21) | POST /summary, /portfolio-summary and four /orders routes exist. Say "GET only, except the POSTs listed under CORS". |
| CORS: "GET only, except POST /summary/{con_id} and POST /portfolio-summary" (l.35) | Also POST /orders, /orders/preview, /orders/{id}/cancel, /orders/{id}/modify (`main.py:39`). |
| Sign-in "commands login_state / saved_login / sign_in / reconnect / cancel_sign_in / sign_out" (l.22) | There is no `reconnect` command (`lib.rs:415`); Reconnect shows the sign-in form again (`App.jsx` `reconnectSession`). |
| "GET /health returns {"connected": bool}" (l.43) | Also `port`, `problem`, `problem_for_s` when disconnected (`routers/app.py`); line 27 knows this. |
| "Broker: … paper trading account, port 4002" (l.6) | Trading works on paper or live; the app's Gateway uses port 4012. |
| "AI_MODEL in .env … the single place to change it" (l.9) | The app has a model picker in Settings, and `usage_store.PRICES` must list every model. |
| Milestones list (l.77–88) | Stops at milestone 5; "Next after milestone 5: Flex", "Trade placement" and "Later: Tauri desktop wrapper" are all done. Copy the README roadmap instead. |
| "Milestone 7 … I merge once the build passes, except #39, #40, #41 and #43" (l.29) | Milestone 7 is finished; remove or move to history. |
| "Stock detail sections: … AI summary placeholder" (l.75) and "AI and Trade buttons are placeholders until milestones 5 and 6" (l.76) | Both are real features now; only the Overview AI card is still a placeholder (#22). |
| "Source: Figma file … (Overview + Positions, light + dark, Components frame)" (l.63) | The file also has the Trading (M6) and Desktop app (M7) pages and the Sentiment Arrows component. |
| Project layout lists 6 backend modules (l.11) | There are 20 (e.g. `yahoo.py`, `trading.py`, `lots.py`, `news_sentiment.py`, `usage_store.py`, `ib_connection.py`). Point to docs/architecture.md section 3 instead of listing them. |
| Git workflow: "One GitHub issue per milestone, one branch per milestone (feature/<name>)" (l.90) | In practice: one branch and PR per issue, `feature/` or `fix/`. |
| "README was updated at the end of milestone 4 (screenshots in docs/screenshots/)" (l.98) | The README changes every PR; the screenshots are still from milestone 4 (see D4). |

- **Why it matters:** CLAUDE.md is the instruction file every Claude session follows. A wrong statement there gets copied into new code and PRs (for example "GET-only" when adding an endpoint).
- **Fix:** one docs PR going through the table. Long lines 21 and 33 (over 2,500 characters each) would be easier to keep current as short bullet lists.

### D3. README feature list and roadmap (S)
- **Where:** README "Planned" ("Purchase dates in the app's Settings and the Your position section (the backend is ready; they need a design)") and Roadmap Milestone 5.1 ("…Settings rows, manual entry and the Your position section wait for a design").
- **Reality:** the Your position cards shipped in #184; only the Settings rows and manual entry are still waiting.
- **Fix:** remove "and the Your position section" from both.

### D4. README screenshots are from milestone 4 (S)
- **Where:** README "Screenshots" (Overview, Positions, Stock detail).
- **Why it matters:** the public README doesn't show Markets, Orders, the order ticket, watchlists, AI summaries or the Mac app, which are the most interesting parts for a portfolio piece.
- **Fix:** rerun `scripts/screenshots.mjs` on the paper account and add a few new rows. Needs Gateway, so it's for a day when you're at the computer.

### D5. Smaller doc and comment drift (S)
- `backend/app_main.py:18`: docstring says secrets come "from the Keychain"; the Keychain was removed (`ff2293c`).
- `backend/main.py:30` (`PathCORS` docstring): "GET + POST for the summaries"; it also covers orders.
- `docs/architecture.md` section 6: "Anthropic API key, Flex token: backend memory only (Mac app)". The Mac app has no way to send a Flex token (see E1).
- README API table: `GET /portfolio-summary/history/{id}` vs the code's `{summary_id}`.
- `frontend/src-tauri/Cargo.toml` still says `version = "0.1.0"`. It's unused, but it looks like the real version. Set it to `0.0.0` with a comment, or keep it in step.

---

## 2. Dead or duplicated code

The automated checks found almost no dead code: every frontend export and CSS class is used (one class is built dynamically: `ai-point-${kind}`), `pyflakes` reports nothing, and every backend function is called. The duplication below matters more.

### X1. Markets and Watchlist pages copy the same logic (M)
- **Where:** `pages/Markets.jsx` and `pages/Watchlist.jsx`, with:
  - the same price-loading effect (`missingIds` → `fetchPrices` → reset on `refreshKey`);
  - the same 350 ms search delay (`SEARCH_DELAY_MS`);
  - the same "holding or not-owned stock" detail object (`{ ...selected, quote, last: quote?.last, not_owned: true }`);
  - `const MARKETS = ['All', 'ASX', 'US']`, which is also in `components/HoldingsList.jsx`.
- **Why it matters:** a fix to one copy (e.g. retrying failed prices, see E4) has to be made twice.
- **Fix:** a `usePrices(conIds, refreshKey)` hook, a `useStockSearch(query)` hook, a `detailFor(stock, holdings, prices)` helper in `lib/holdings.js`, and `MARKETS` in `lib/listPanes.js`.

### X2. Three menu implementations (M)
- **Where:** `components/AccountCard.jsx` (its own menu with arrow keys), `components/PopupMenu.jsx` (watchlists, with arrow keys), `components/detail/SummaryHistoryMenu.jsx` (Escape and click outside only, no arrow keys).
- **Why it matters:** the three behave slightly differently from the keyboard, and fixes don't carry over.
- **Fix:** make AccountCard and SummaryHistoryMenu use `PopupMenu` (it would need an optional header block for the account name and status).

### X3. Two near-identical summary streaming routes (M)
- **Where:** `backend/routers/summaries.py`: `generate_summary` and `generate_portfolio_summary` each:
  - lock, send `status`, build the facts, send `facts`;
  - loop over `stream_sections`;
  - save, record usage, send `done`;
  - map errors in the same way.
- **Fix:** one helper `stream_summary(lock, build, stream, save, respond)` used by both, so error handling and usage logging live in one place.

### X4. localStorage reads and writes repeated in five files (S)
- **Where:**
  - `components/detail/DisclosureSection.jsx`
  - `hooks/appearance.js`
  - `hooks/useResizableWidth.js`
  - `lib/watchlists.js`
  - `pages/Markets.jsx`

  Each has its own `try { JSON.parse(localStorage…) } catch {}`.
- **Fix:** `lib/storage.js` with `readJson(key, fallback)` and `writeJson(key, value)`.

### X5. Formatting helpers live inside `summary_facts.py` (S)
- **Where:** `backend/portfolio_facts.py:7` imports `money`, `pct`, `long_date`, `as_of_text`, `change_pct` and `parse_money` from `summary_facts.py`.
- **Why it matters:** the portfolio summary depends on the stock summary module just for number formatting, which makes splitting `summary_facts.py` (F1) harder.
- **Fix:** move them to `backend/facts_format.py`.

---

## 3. Files doing too many jobs

### F1. `backend/summary_facts.py` (616 lines) (M)
- **Jobs:** formatting helpers, purchase-lot summaries, the stock facts sheet (`build_facts` alone is 273 lines), the "why the price moved since last time" maths (`since_last_move` and seven helpers), saved-facts parsing and the history compare (`compare_data`).
- **Fix:** split into:
  - `facts_format.py` (X5);
  - `since_last.py` (lines 403–535);
  - `summary_compare.py` (`parse_money`, `compare_data`);
  - `summary_facts.py`, keeping only the sheet.

  Inside `build_facts`, each `# --- D:… ---` block can become its own small function. That also makes T2 easier.

### F2. `frontend/src/App.jsx` (436 lines, 16 `useState`, 7 `useEffect`) (M)
- **Jobs:** health polling, loading account/positions/quotes, the Mac-app startup and sign-in screens, page switching, the order ticket and confirm flow, the Settings sheet, watchlist navigation and the ⌘⌥S shortcut.
- **Fix:**
  - a `useConnection()` hook (health polling, `connectionState`);
  - a `usePortfolioData(connected)` hook (load, refresh, `dataVersion`);
  - a `<TradeFlow>` component that owns the ticket state;
  - a `<PageContent page=…>` switch.

  App.jsx would then mostly wire these together.

### F3. `frontend/src/pages/Setup.jsx` (437 lines, 8 screens) (S)
- **Jobs:** Startup, Welcome, Install Gateway, Sign in, Approve on phone, Login not approved, the countdown hook and the setup state machine.
- **Fix:** a `pages/setup/` folder with one file per screen. It's a mechanical move with no behaviour change, so it's a good first refactor once the freeze ends.

### F4. `frontend/src/components/OrderTicket.jsx` (345 lines) (M)
- **Jobs:** order maths (`amountPrice`, `sharesForAmount`, `orderFrom`, commission text, totals, buying power, switching between shares and amount), the delayed preview request, and the form.
- **Fix:** move the maths into `lib/orderTicket.js` as plain functions. The component gets smaller and the maths becomes testable (T1).

### F5. Also large (S each, lower priority)
- `backend/routers/summaries.py` (373 lines): stock facts gathering, portfolio facts gathering, both streaming routes, history and `/usage`. After X3, move the facts gathering to `summary_inputs.py`.
- `frontend/src/index.css` (4,065 lines): one file for every screen. Split by area (`base.css`, `sidebar.css`, `detail.css`, `trading.css`, `setup.css`, `watchlists.css`), imported from `main.jsx`.
- `frontend/src-tauri/src/lib.rs` (447 lines): backend process, sign-in commands, Keychain clean-up, settings, Gateway install, API key, window and menu. Move the commands into `commands.rs` and the backend process into `backend.rs`.

---

## 4. Missing tests for risky logic

The frontend has 2 test files (`lotCards`, `watchlists`). The backend has 110 tests, which cover trading guardrails, orders, Flex, lots, summaries, the portfolio summary, sentiment and usage well.

### T1. Order ticket maths (M) — the most important gap
- **Where:** `OrderTicket.jsx`:
  - `sharesForAmount`, which uses `Math.floor(amount / price + 1e-6)`;
  - `amountPrice`;
  - `orderFrom`;
  - the switch between shares and amount, which rounds up to the cent;
  - the estimated total, where commission is added for a buy and subtracted for a sell, but only in the same currency;
  - the buying-power estimate.
- **Why it matters:** this decides how many shares are sent to IBKR. The backend re-checks whole shares, the value limit and selling more than you hold, but it can't know what you meant to buy.
- **Cases worth testing:**
  - amount 1000 at US$342.76000975 gives 2 shares;
  - an amount that divides exactly isn't rounded down by floating-point noise;
  - switching shares → amount → shares gives the same count back;
  - a market order uses the latest price and a limit order uses the limit;
  - a sell total subtracts commission;
  - different currencies show the value without commission;
  - odd input: "1e3" and "0x10" pass `Number()` as 1000 and 16, "1,000" gives no order, "1.5" shares reaches the backend and is refused there.
- **Fix:** after F4, a `lib/orderTicket.test.js` with these cases. Consider rejecting anything that isn't plain digits (with an optional decimal point) before `Number()`.

### T2. Backend logic without tests (M)
| Logic | Where | Why it's risky |
|---|---|---|
| `since_last_move` and helpers | `summary_facts.py:403–535` | Beta, volatility, trading-day counting across time zones; decides "company specific" vs "in line with the market" in every summary |
| `compare_data` | `summary_facts.py:561` | The exact "what changed" numbers in compare mode |
| News headline filter (`_title_patterns`, `_fetch_news`) | `yahoo.py:151–190` | Decides which headlines are "about this company" (e.g. the APA / BHP bare-ticker rule) |
| `mask_secrets` | `secrets_guard.py` | The only thing between the API key or Flex token and the logs |
| Client ID fallback (error 326) | `ib_connection.py` | Lets the app and dev backend run together |
| Failure memory in `cached()` | `cache.py` | A wrongly remembered failure hides a section for 60 s |
| `display_name` (28-character cut-off) | `names.py` | Company names everywhere |

- **Fix:** start with `mask_secrets` and `since_last_move`, which are pure functions with a high cost if wrong.

### T3. Frontend pure helpers without tests (S)
- `lib/holdings.js` `buildHoldings` (currency conversion and portfolio weights), `lib/summaryDiff.js` (compare tags), `lib/format.js` (money, percent, `formatAge`), and the snap and collapse logic in `hooks/useResizableWidth.js`.

---

## 5. Error handling gaps

| Service | What you see now | Gap |
|---|---|---|
| IB Gateway down | ConnectionMessage, data hidden or dimmed; 503s per request | Good. Error 10197 (live session elsewhere blocks prices) is handled quietly but never explained, so prices look "missing". |
| Yahoo Finance | That section says "unavailable" | Never retried until you open another stock (E4). |
| Flex | "Unknown" purchase dates | `GET /lots/status` returns `last_error`, but nothing shows it (E5). |
| Anthropic (summaries) | Clear messages per error code | Good. |
| Anthropic (news sentiment) | Headlines without arrows | Silent by design; a wrong key isn't mentioned anywhere except the summary section. Fine for now. |
| Backend not running | Toolbar "Waiting for the backend…" | In the Mac app the error box still says "port 8000" (E4). |

### E1. "Set up Flex in Settings" leads nowhere (S / M)
- **Where:** `frontend/src/lib/lotCards.js:22` shows "Set up Flex in Settings" when Flex isn't configured. `pages/Settings.jsx` has no Flex rows, and the Mac app never sends `flex_token` / `flex_query_id` (`lib.rs` only sends the Anthropic key and `ib_port`; `docs/flex-query.md` says the rows are waiting for a design).
- **Why it matters:** in the Mac app, purchase and CGT dates can't be turned on at all, and the hint sends people to a screen without the option.
- **Fix now (S):** change the hint to something true, e.g. "Purchase dates need an IBKR Flex Query (docs/flex-query.md)" in development, or "Coming soon" in the app.
- **Real fix (M):** the Settings rows, once they have a Figma design.

### E2. Placing an order: uncertain outcome (M)
- **Where:** `components/OrderConfirm.jsx` `place()` and the `watchOrders(...).catch(() => {})` at line 98.
- **Why it matters:**
  - **Network error while placing:** if `POST /orders` fails partway (a timeout, the backend restarting), the sheet shows the error text, such as "Load failed". But IBKR may already have the order. The confirmation token is single use, so pressing Place again is refused, which is safe. Nothing tells the user to check the Orders page, though.
  - **Update stream drops:** if the stream fails after placing, the sheet stays on its last status ("Submitted") with no sign that updates stopped.
- **Fix:**
  - after a failed Place, show "We couldn't confirm the order. Check Orders before trying again" with a View Orders button;
  - when the stream ends without a final status, show "Live updates stopped. Check Orders for the latest status".

### E3. Links probably don't open in the Mac app (S to verify, M to fix)
- **Where:** news items (`NewsSection.jsx:41`), summary citations (`SummaryView.jsx:34`) and the company website (`AboutSection.jsx:52`) use `<a target="_blank">`. The Tauri app has no opener plugin and no new-window handler (`src-tauri/capabilities/default.json`, `lib.rs`), and the update prompt needed its own Rust command (`open_release_page`) to open a link.
- **Why it matters:** clicking a headline in the app may do nothing.
- **Fix:** check in the app first. If they don't open, add `tauri-plugin-opener`, or one Rust command that opens `http(s)` links in the default browser, and use it from these three places.

### E4. Error messages and retries (M)
- **"port 8000" in the Mac app:** `App.jsx:336` "Make sure the backend is running on port 8000…" shows in the Mac app too, where the backend runs on a random port. Use the app wording ("The app's backend isn't responding; quit and reopen it") when `IN_APP`.
- **No request timeouts:** `lib/api.js` has none, so a request the backend never answers leaves a section loading forever. Add `AbortSignal.timeout(…)` (e.g. 30 s, longer for previews and streams).
- **Sections never retry:** `hooks/useFetch.js` only refetches when the stock changes. After a short Yahoo outage, "unavailable" stays until you open another stock, and Refresh doesn't help. Pass `refreshKey` into the sections' keys, or add a "Try again" link to `SectionUnavailable`.
- **Failed prices stay blank:** in Markets and Watchlist, failed price requests are swallowed (`.catch(() => {})`). The rows show "—" until the next refresh, with no hint why. Fold this into X1's `usePrices` with one retry.

### E5. Flex errors are recorded but never shown (S)
- **Where:** `backend/lots.py:72` returns `last_error`; `HoldingDetail.jsx:77` only reads `configured`.
- **Fix:** when `last_error` is set, show it under "Unknown" in the Purchase date card (it's already masked).

---

## 6. Security and dependencies

**What's good:**
- No secrets are tracked or in the git history (`.env`, `*.key`, `data/` and the sqlite files are ignored).
- `pip-audit` finds no known vulnerabilities in the Python packages.
- The Mac app checks its access token with `secrets.compare_digest`.
- The backend only listens on 127.0.0.1.
- The window has a strict content security policy.
- The IBKR password only travels over stdin.
- Every POST checks the Origin header.

### S1. `npm audit`: 1 high-severity issue (S)
- `source-map-js` 1.0.0–1.2.1 (GHSA-68fv-2mgg-jv7q, denial of service from a crafted source map). It's only used by the build tools (Vite), not shipped in the app, so the real risk is low.
- **Fix:** `npm audit fix` (a lock file update), then build. Also available: vite 8.3.4, react 19.3.1, oxlint 1.88, @vitejs/plugin-react 6.1.2; backend anthropic 1.15.0, fastapi 0.143.3. All patch or minor updates.

### S2. Links from Yahoo aren't checked to be web links (S)
- **Where:** `yahoo.py:187` passes Yahoo's `link` straight through; the profile `website` likewise.
- **Why it matters:** low risk today, because React 19 blocks `javascript:` links and the Mac app's content security policy blocks inline scripts. But a check in the backend would protect any future link handler (E3).
- **Fix:** keep only `http://` and `https://` URLs in `yahoo.py`.

### S3. Build tools mixed into `requirements.txt` (S)
- `requirements.txt` is a full `pip freeze`, so PyInstaller (only needed to build the Mac app) sits with the runtime packages, and there is no list of the packages the code actually uses.
- **Fix:** `requirements.in` with the direct dependencies, and `requirements-build.txt` for PyInstaller. Low priority.

---

## 7. Inconsistencies

### I1. Two ways of loading data in the frontend (S)
- `useFetch` (profile, lots, summaries) versus hand-written `useEffect` + `ignore` flags (price history in `HoldingDetail`, prices in Markets and Watchlist, Orders).
- **Fix:** use `useFetch` everywhere it fits (after E4 adds refresh and retry to it).

### I2. Generic list styles named after holdings (S)
- Markets and Watchlist rows use `holding-item`, `holdings-pane` and `holdings-list` classes, and the shared hook stores `holdingsListWidth`.
- **Fix:** rename to `stock-row`, `list-pane` and `stock-list` when touching those files anyway.

### I3. Hard-coded colours instead of theme variables (S)
- `index.css:3828` (`.rename-field`, added in #189) uses `rgba(0, 122, 255, 0.25)` instead of `var(--focus-ring)`, so dark mode gets the light-mode blue.
- `index.css:3418` uses `rgba(0, 122, 255, 0.14)`.
- About 40 other lines use literal colours for shadows and white text, which is fine.
- **Fix:** use the variables for the two accent colours.

### I4. Names that say more than the code does (S)
- `saved_credentials()` in `lib.rs:128` returns only the username (the password is never saved). Rename to `saved_username_for_restart()`.

### I5. Pages behave differently when the IBKR session ends (S)
- Positions and Overview stay visible (dimmed) after the session ends; Markets, Orders and watchlists disappear (`App.jsx`, `connected` checks). That's reasonable, since they need live prices, but it isn't explained on screen.
- **Fix:** show the same "session ended" message in place of those pages, instead of nothing.

### I6. Branch names (S)
- Branches are `feature/…` and `fix/…`; CLAUDE.md only mentions `feature/<name>` (see D2).
