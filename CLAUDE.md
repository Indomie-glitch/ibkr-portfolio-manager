IBKR Portfolio Manager

A cleaner, more intuitive portfolio dashboard for Interactive Brokers, with AI generated stock summaries. Personal learning project and portfolio piece, built to look professional on GitHub.

Stack
Broker: IB Gateway running locally, paper trading account, port 4002
Backend: Python 3.11, FastAPI, uvicorn, ib_async (the maintained fork of ib_insync; do not use ib_insync), yfinance for data IB doesn't provide
Frontend: React with Vite, in frontend/
AI summaries: Claude API, model set by AI_MODEL in .env (default claude-haiku-4-5, the single place to change it), key in .env as ANTHROPIC_API_KEY (backend only, never sent to the frontend)
Project layout
backend/         FastAPI app (main.py), config.py (loads .env, DATA_DIR), app_main.py + portfolio-backend.spec (PyInstaller entry for the Mac app), ibkr_hello.py, requirements.txt, venv/
frontend/        React app (Vite); frontend/src-tauri/ is the Mac app shell (Tauri 2, Rust)
.env             real settings, gitignored, never commit
.env.example     template for .env, committed
README.md
Running locally
IB Gateway must be running and logged in to the paper account
Backend: cd backend && source venv/bin/activate && uvicorn main:app --reload (port 8000)
Frontend: cd frontend && npm run dev (port 5173)
Mac app: cd frontend && npm run tauri dev (uses your own backend on 8000) or npm run build:app (PyInstaller backend bundled as a resource via src-tauri/tauri.release.conf.json; Rust starts it with PORTFOLIO_DATA_DIR = Application Support, keeps its stdin open so it exits with the app, SIGTERM on quit). Handshake: Rust picks a free port and a random per-launch token, passes the token as the first stdin line (--token-stdin), and injects window.__PORTFOLIO_BACKEND__ = {url, token} into the window (created in lib.rs, not tauri.conf.json); api.js sends X-App-Token on every request and the backend's require_app_token middleware returns 401 without it (dev has no token). The frontend shows 'Starting…' for up to 30 s, then 'not running'. Keychain (src-tauri/src/secrets.rs, keyring crate, service com.indomieglitch.portfoliomanager, names anthropic_api_key and ibkr_password): only Rust reads it; commands secret_status / save_secret / delete_secret (frontend/src/appSecrets.js) never return values; the Anthropic key goes to the backend as a stdin message {"set_secret": ...} (read in a background thread after the window opens) and lives only in config.SECRETS; in development the key still comes from .env (config.anthropic_api_key()). Settings page (frontend/src/pages/Settings.jsx, sidebar App > Settings): API key (Keychain), Gateway port and appearance; works while disconnected. Non-secret settings live in settings.json in Application Support (src-tauri/src/settings.rs, commands get_settings / save_settings, frontend/src/appSettings.js) and reach the backend as {"set_setting": "ib_port"} over stdin; keep_connected reads config.ib_port() each attempt and reconnects when it changes. The backend API stays GET-only. Rust is in ~/.cargo/bin (rustup didn't edit the shell profile), so prefix PATH="$HOME/.cargo/bin:$PATH".
Milestone 7 (Mac app for a friend, issues #34-#43): one branch and PR each; I merge #34, #35, #36, #38, #37 once the build passes, the user reviews #39, #40, #41, #43 before merging.
Backend rules
Connect to IB Gateway via a background task started in the FastAPI lifespan (keep_connected in main.py), using await ib.connectAsync(...); it retries every 5s so the server starts without Gateway and reconnects after drops. IB endpoints use Depends(require_ib) and return 503 while disconnected. Never use ib.connect() inside the server (it conflicts with uvicorn's event loop).
Any endpoint that touches ib must be async def, and should use the async versions of ib_async methods where they exist (e.g. accountSummaryAsync).
Connection is read only (readonly=True). Do not add order placement until milestone 6.
Connection settings (IB_HOST, IB_PORT, IB_CLIENT_ID) come from .env via python-dotenv.
CORS allows http://localhost:5173, http://127.0.0.1:5173 and tauri://localhost (the Mac app window). GET only, except POST /summary/{con_id} (generating an AI summary), which PathCORS in main.py allows from those origins only; the endpoint also checks the Origin header, since simple cross-site POSTs skip the preflight.
After installing any Python package, run pip freeze > requirements.txt from backend/ with the venv active.
Current API
GET /health returns {"connected": bool}
GET /positions returns a list of {"con_id", "symbol", "name", "name_truncated", "sec_type", "currency", "exchange", "quantity", "avg_cost", "market_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct"} (from ib.portfolio(); names from contract details, cached, title-cased by backend/names.py; IB cuts longName at 28 characters, which sets name_truncated)
GET /account returns net_liquidation, cash, positions_value, buying_power, currency, unrealized_pnl, fx_rates ({currency: rate to base})
GET /quotes returns a list of {"con_id", "last", "prev_close", "day_change", "day_change_pct", "source"}. Tries delayed quotes (reqMarketDataType(3)); if IB sends none, source is "history" and day change comes from daily bars. Quote requests are skipped for 10 min after an empty answer.
GET /history/{con_id}?range=1D|1W|1M|3M|1Y|All returns {"con_id", "range", "bars": [{"time", "close"}]} via reqHistoricalDataAsync, cached 60s
GET /quotes also returns open, day_high, day_low, bid, ask, volume, avg_volume (volume and the 3-month average both from IB daily bars, so they match; IB volume runs below Yahoo's consolidated volume)
GET /profile/{con_id} (About; cached 1h), /stats/{con_id} (slow key statistics; cached 1h, shares one Ticker.info call with /profile), /news/{con_id} (cached 15 min), /performance/{con_id} (cached 1 day). Yahoo failures return 502 so only that section shows "unavailable"; unmapped exchanges return 404.
Yahoo rules (backend/yahoo.py): yahoo_symbol(contract) is the only IB -> Yahoo mapping (ASX -> .AX). yfinance is blocking, so calls run via asyncio.to_thread, one at a time (its SQLite cache errors with "database is locked" under parallel use). Caching via cached() in backend/cache.py (per-key lock, failures remembered 60s). News uses yf.Search by company name (Ticker.news returns 404); headlines must name the company; a bare ASX ticker counts only if the US company with that ticker is the same company. Benchmarks are total return indexes: ^AXJT and ^SP500TR.
AI summary (backend/summary_facts.py, ai_summary.py, summary_store.py):
  GET /summary/{con_id} returns the last saved summary and ai_configured; POST /summary/{con_id} streams Server-Sent Events (status, facts, section, done, error); GET /summary/{con_id}/facts previews the facts sheet (no API call).
  History: GET /summary/{con_id}/history (id, created_at, model, price; newest first), GET /summary/{con_id}/history/{summary_id} (one in full, same shape as latest), GET /summary/{con_id}/compare?a=&b= (older, newer, data_changes from compare_data in summary_facts.py). summary_store keeps the last 20 per stock (KEEP_PER_STOCK), pruned on save.
  Compare tags (frontend/src/summaryDiff.js) match points by wording, so they are a guide only; data_changes are exact. Moves under 1% of the old value are not tagged "Changed" and are marked minor in the data strip (MINOR_CHANGE_PCT in both files).
  All numbers are calculated in summary_facts.py; the model only explains them. Every facts block has an id (D:..., news N1...) and the response schema limits citations to those ids; unknown ids are removed and uncited points flagged anyway.
  10 fixed sections via structured outputs (output_config.format json_schema); sections are streamed as soon as each completes (jiter partial parsing). Summaries are saved in data/summaries.sqlite (gitignored); section 10 compares with the previous one.
  Section 10 (since_last_move in summary_facts.py): stock vs price index (^AXJO / ^GSPC) over exactly the window between summaries, using the index level saved with the previous summary (benchmark_level), else Yahoo 5-minute bars (about a month, cached 5 min), else daily closes. expected = beta x benchmark, residual = stock - expected, typical = 60-day daily volatility x sqrt(trading days, fractional); company specific if |residual| > 1.5 x typical; small_move if |stock| < typical; 1 percentage point rule only when beta or volatility is missing. Only news published between the summaries is offered; automatic checks flag causal wording, news cited for in-line moves and news outside the window.
  Purchase dates are unknown (IB's API has none); peers and sector performance are not available.
IB limits: about 60 history requests per 10 minutes, so history is cached. Error 10197 ("competing live session") means the live account is logged in elsewhere (TWS, mobile, web), which blocks market data on the paper account; history still works.
Design
Source: Figma file e8rdacwgUA1ZtyNaw81Ry7 (Overview + Positions, light + dark, Components frame). Figma MCP calls are limited, so do not re-fetch it; use the values below.
Style: macOS-like. Font Inter (400/500/600/700). Plain CSS with CSS variables in frontend/src/index.css; dark set is active when <html data-theme="dark">, set by useAppearance (frontend/src/appearance.js) from the toolbar's System/Light/Dark control, saved in localStorage. No Tailwind, no chart library (charts are hand-drawn SVG).
Icons: frontend/src/components/icons.jsx (paths copied from the Figma SVGs), drawn with currentColor.
Colours (light / dark):
  bg #ffffff / #1e1e1e; sidebar panel #f2f2f6 / #262628; surface-2 (stat cards) #f5f5f7 / #2c2c2e
  text #1d1d1f / #f5f5f7; text-2 #6e6e73 / #98989d; text-3 #8e8e93 (both)
  border rgba(0,0,0,.08) / rgba(255,255,255,.11); row border .06 / .08; fill (pills, active item) rgba(0,0,0,.06-.07) / rgba(255,255,255,.08-.10)
  accent #007aff / #0a84ff; gain text #248a3d / #30d158; loss text #d70015 / #ff453a; day-change pills #34c759 and #ff3b30 with white text
  delayed badge bg rgba(255,149,0,.12), text #b25f00 / #ff9f0a
  allocation palette #007aff #5856d6 #30b0c7 #ff9500 #ff2d55 (dark #0a84ff #5e5ce6 #40c8e0 #ff9f0a #ff375f)
Layout: sidebar 256px; toolbar 12px/28px padding; page body padding 28px, gap 22px; cards radius 14px; buttons are pills (radius 999px)
Type scale: page title 15/700; net liquidation 36/700; stat value 22/600; holding price 42/700; body 13; captions 11
Stock detail sections (Figma node 11:260, read once): collapsible sections below "Your position" (DisclosureSection, open state in localStorage "detailSections", closed sections don't fetch): Key statistics, About, AI summary placeholder, News, Performance. Sections adapt to the detail panel width with a container query.
Screens: Overview (net liquidation, 3 stat cards, positions table, allocation donut, AI summary card). Clicking a row opens that holding on Positions (resizable list 220-480px, holding detail with price chart, position stats, AI summary card). AI and Trade buttons are placeholders until milestones 5 and 6.
Milestones
Connect to IB Gateway (done)
Backend REST API (done)
Minimal React UI: account summary and positions table (done)
Polished UI (done, PR #7, issue #6)
Milestone 4.5: Expanded stock detail with yfinance (done, PR #9, issue #8)
AI stock summaries via Claude API (done, PR #11, issue #10)
Summary history and compare (done, PR #46, issue #12)
Explain price changes since the last summary (in progress, issue #45, branch feature/explain-price-changes)
Next after milestone 5: IB Flex Query purchase dates per lot (each with its own 12-month CGT date), manual entry as fallback
Trade placement
Later: Tauri desktop wrapper
Git workflow
One GitHub issue per milestone, one branch per milestone (feature/<name>), merged via pull request with Closes #<issue> in the body
Small commits with conventional messages: feat:, fix:, refactor:, docs:, chore:
Tiny docs changes can go straight to main
Never commit .env, venv/, or node_modules/
Use the gh CLI for issues and PRs
Working with me
I'm a CS student learning as I go. After making changes, briefly explain what you changed and why, and give a short plain explanation of any new technical term.
Show me a plan before large changes.
README was updated at the end of milestone 4 (screenshots in docs/screenshots/); keep its roadmap and API table current.