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
GET /positions returns a list of {"symbol", "quantity", "avg_cost"}
GET /account returns net_liquidation, cash, positions_value, buying_power, currency
Milestones
Connect to IB Gateway (done)
Backend REST API (done)
Minimal React UI: account summary and positions table (in progress)
Polished UI
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