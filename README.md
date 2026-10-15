# IBKR Portfolio Manager

A cleaner, more intuitive portfolio dashboard for Interactive Brokers, with AI generated stock summaries.

Interactive Brokers is a powerful broker, but its native interface is dense and hard to navigate. This project connects directly to IBKR through IB Gateway and presents your portfolio in a simpler, modern web interface.

> **Status:** Dashboard working (milestone 4). AI summaries are next.

## Screenshots

| | Light | Dark |
|---|---|---|
| **Overview** | ![Overview, light mode](docs/screenshots/overview-light.png) | ![Overview, dark mode](docs/screenshots/overview-dark.png) |
| **Positions** | ![Positions, light mode](docs/screenshots/positions-light.png) | ![Positions, dark mode](docs/screenshots/positions-dark.png) |

*Paper trading account; prices delayed about 15 minutes.*

## Features

### Working now
* Overview: net liquidation value, cash, buying power and total unrealised P&L
* Sortable positions table (money columns compared in AUD, so US and ASX holdings sort correctly)
* Allocation card that switches between market value, cost basis, quantity and unrealised P&L
* Positions screen: searchable holdings list with an All / ASX / US filter and a resizable sidebar
* Price chart per holding (1D to All) with your average cost marked
* Light, dark or system appearance
* Refreshes every 60 seconds, and recovers on its own if IB Gateway disconnects and comes back

### Planned
* AI generated summaries for stocks in your portfolio (powered by Claude)
* Place trades directly from the app
* Optional desktop app version

## Roadmap

* [x] **Milestone 1:** Connect to IB Gateway (paper trading account)
* [x] **Milestone 2:** Backend REST API exposing account and position data
* [x] **Milestone 3:** Minimal React UI
* [x] **Milestone 4:** Polished UI
* [ ] **Milestone 5:** AI stock summaries via the Claude API
* [ ] **Milestone 6:** Trade placement
* [ ] **Later:** Desktop app wrapper (Tauri)

## Tech Stack

| Layer | Technology |
|---|---|
| Broker connection | Interactive Brokers IB Gateway |
| Backend | Python 3.11, [FastAPI](https://fastapi.tiangolo.com/), [ib_async](https://github.com/ib-api-reloaded/ib_async) (the maintained successor to ib_insync) |
| Frontend | [React](https://react.dev/) with [Vite](https://vite.dev/), plain CSS, hand-drawn SVG charts |
| AI summaries | Claude API (Haiku) |

## Architecture

```
React frontend  <-->  Python REST API  <-->  IB Gateway (localhost:4002)  <-->  Interactive Brokers
                            |
                            v
                        Claude API
```

The React frontend talks only to the Python backend. The backend manages the connection to IB Gateway running locally, and calls the Claude API to generate stock summaries.

## Getting Started

### Prerequisites

* An Interactive Brokers account with a **paper trading** account enabled (created via the IBKR Client Portal)
* [IB Gateway](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php) installed, with API access enabled on port 4002
* Python 3.11
* Node.js 20.19+ or 22.12+ (for the frontend)

### Setup

```bash
git clone https://github.com/Indomie-glitch/ibkr-portfolio-manager.git
cd ibkr-portfolio-manager

# Backend
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Frontend
cd frontend
npm install
```

### Configuration

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key (needed for AI summaries) |
| `IB_HOST` | IB Gateway host, usually `127.0.0.1` |
| `IB_PORT` | IB Gateway port (`4002` for paper trading, `4001` for live) |
| `IB_CLIENT_ID` | API client ID, `1` by default; use a different one if another app is already connected with it |

### Run

Start IB Gateway and log in to your paper account. Then, in two terminals:

```bash
# Terminal 1: API on http://localhost:8000
cd backend
source venv/bin/activate
uvicorn main:app --reload
```

```bash
# Terminal 2: app on http://localhost:5173
cd frontend
npm run dev
```

Open http://localhost:5173. The backend starts even if IB Gateway isn't running yet, and connects as soon as it is.

### API

| Endpoint | Returns |
|---|---|
| `GET /health` | Whether the backend is connected to IB Gateway |
| `GET /account` | Net liquidation, cash, positions value, buying power, unrealised P&L, FX rates |
| `GET /positions` | Each holding with price, market value, unrealised P&L and company name |
| `GET /quotes` | Last price and day change per holding (delayed) |
| `GET /history/{con_id}?range=1M` | Price history for the chart (`1D`, `1W`, `1M`, `3M`, `1Y`, `All`) |

**Note on market data:** if your live IBKR account is logged in somewhere else (TWS, the mobile app or the web portal), IB blocks quotes on the paper account (error 10197). The app then works out day change from IB's daily price history instead.

## Project Structure

```
ibkr-portfolio-manager/
├── backend/          FastAPI app (main.py), IB Gateway connection, REST API
├── frontend/         React app (Vite)
├── docs/screenshots/ Screenshots used in this README
├── .env.example      Template for environment variables
└── README.md
```

## Disclaimer

This is a personal project and is not affiliated with Interactive Brokers. It is intended for use with a paper trading account. Nothing in this project is financial advice, and you use it with real money at your own risk.