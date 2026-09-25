# IBKR Portfolio Manager

A cleaner, more intuitive portfolio dashboard for Interactive Brokers, with AI generated stock summaries.

Interactive Brokers is a powerful broker, but its native interface is dense and hard to navigate. This project connects directly to IBKR through IB Gateway and presents your portfolio in a simpler, modern web interface.

> **Status:** Early development. Currently building the broker connection and backend API.

## Features

### Planned
* View account summary, positions and P&L in a clean dashboard
* AI generated summaries for stocks in your portfolio (powered by Claude)
* Place trades directly from the app
* Optional desktop app version

## Roadmap

* [ ] **Milestone 1:** Connect to IB Gateway (paper trading account)
* [ ] **Milestone 2:** Backend REST API exposing account and position data
* [ ] **Milestone 3:** Minimal React UI
* [ ] **Milestone 4:** Polished UI
* [ ] **Milestone 5:** AI stock summaries via the Claude API
* [ ] **Milestone 6:** Trade placement
* [ ] **Later:** Desktop app wrapper (Tauri)

## Tech Stack

| Layer | Technology |
|---|---|
| Broker connection | Interactive Brokers IB Gateway |
| Backend | Python 3.11, [ib_insync](https://github.com/erdewit/ib_insync) |
| Frontend | React (planned) |
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
* Python 3.11 (note: `ib_insync` does not currently work on Python 3.14)

### Setup

```bash
git clone https://github.com/Indomie-glitch/ibkr-portfolio-manager.git
cd ibkr-portfolio-manager/backend

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
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

### Run

Start IB Gateway and log in to your paper account, then:

```bash
python ibkr_hello.py
```

## Project Structure

```
ibkr-portfolio-manager/
├── backend/          Python backend (IB Gateway connection, REST API)
├── frontend/         React app (coming soon)
├── .env.example      Template for environment variables
└── README.md
```

## Disclaimer

This is a personal project and is not affiliated with Interactive Brokers. It is intended for use with a paper trading account. Nothing in this project is financial advice, and you use it with real money at your own risk.