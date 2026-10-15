IBKR Portfolio Manager

A cleaner, more intuitive portfolio dashboard for Interactive Brokers, with AI generated stock summaries. Personal learning project and portfolio piece, built to look professional on GitHub.

Stack
Broker: IB Gateway running locally, paper trading account, port 4002
Backend: Python 3.11, FastAPI, uvicorn, ib_async (the maintained fork of ib_insync; do not use ib_insync)
Frontend: React with Vite, in frontend/
AI summaries: Claude API (Haiku), key in .env as ANTHROPIC_API_KEY
Project layout
backend/         FastAPI app (main.py), ibkr_hello.py, requirements.txt, venv/
frontend/        React app (Vite)
.env             real settings, gitignored, never commit
.env.example     template for .env, committed
README.md
Running locally
IB Gateway must be running and logged in to the paper account
Backend: cd backend && source venv/bin/activate && uvicorn main:app --reload (port 8000)
Frontend: cd frontend && npm run dev (port 5173)
Backend rules
Connect to IB Gateway once at startup via FastAPI lifespan, using await ib.connectAsync(...). Never use ib.connect() inside the server (it conflicts with uvicorn's event loop).
Any endpoint that touches ib must be async def, and should use the async versions of ib_async methods where they exist (e.g. accountSummaryAsync).
Connection is read only (readonly=True). Do not add order placement until milestone 6.
Connection settings (IB_HOST, IB_PORT) come from .env via python-dotenv.
CORS allows http://localhost:5173 and http://127.0.0.1:5173, GET only for now.
After installing any Python package, run pip freeze > requirements.txt from backend/ with the venv active.
Current API
GET /health returns {"connected": bool}
GET /positions returns a list of {"con_id", "symbol", "name", "sec_type", "currency", "exchange", "quantity", "avg_cost", "market_price", "market_value", "unrealized_pnl", "unrealized_pnl_pct"} (from ib.portfolio(); names from contract details, cached)
GET /account returns net_liquidation, cash, positions_value, buying_power, currency, unrealized_pnl, fx_rates ({currency: rate to base})
GET /quotes returns a list of {"con_id", "last", "prev_close", "day_change", "day_change_pct", "source"}. Tries delayed quotes (reqMarketDataType(3)); if IB sends none, source is "history" and day change comes from daily bars. Quote requests are skipped for 10 min after an empty answer.
GET /history/{con_id}?range=1D|1W|1M|3M|1Y|All returns {"con_id", "range", "bars": [{"time", "close"}]} via reqHistoricalDataAsync, cached 60s
IB limits: about 60 history requests per 10 minutes, so history is cached. Error 10197 ("competing live session") means the live account is logged in elsewhere (TWS, mobile, web), which blocks market data on the paper account; history still works.
Design
Source: Figma file e8rdacwgUA1ZtyNaw81Ry7 (Overview + Positions, light + dark, Components frame). Figma MCP calls are limited, so do not re-fetch it; use the values below.
Style: macOS-like. Font Inter (400/500/600/700). Plain CSS with CSS variables in frontend/src/index.css; dark mode via prefers-color-scheme. No Tailwind, no chart library (charts are hand-drawn SVG).
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
Screens: Overview (net liquidation, 3 stat cards, positions table, allocation donut, AI summary card). Clicking a row opens that holding on Positions (resizable list 220-480px, holding detail with price chart, position stats, AI summary card). AI and Trade buttons are placeholders until milestones 5 and 6.
Milestones
Connect to IB Gateway (done)
Backend REST API (done)
Minimal React UI: account summary and positions table (done)
Polished UI (in progress, issue #6)
AI stock summaries via Claude API
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
The README still mentions ib_insync and is not final; we'll update it at the end.