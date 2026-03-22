# CoinSpot AI Trading Bot

An autonomous cryptocurrency trading bot powered by **Claude AI** (Anthropic) that trades on the [CoinSpot](https://www.coinspot.com.au) exchange. Includes a real-time React dashboard with WebSocket updates.

## Features

- **Claude-powered decisions** — Claude analyses prices, open positions, trade history, and bot memory every 60 seconds
- **Paper mode** — simulate trades with a configurable AUD balance before going live
- **Hard-coded risk limits** — 4% stop loss, 8% take profit, max 5 open positions, max 10% per trade
- **Persistent memory** — SQLite DB + JSON backup so the bot remembers past decisions across restarts
- **Real-time dashboard** — React + Tailwind with WebSocket live updates: prices, open trades, trade history, AI reasoning, memory viewer

## Architecture

```
backend/
  main.py          — FastAPI app + WebSocket server
  bot.py           — Core bot loop (runs every 60s via APScheduler)
  coinspot.py      — CoinSpot REST API client (HMAC-SHA512)
  claude_brain.py  — Claude AI decision engine
  database.py      — SQLite + JSON backup memory system
  risk.py          — Stop loss / take profit / position sizing
  config.py        — Environment variable loader
frontend/
  src/
    App.jsx
    components/
      Dashboard.jsx        — Balance, PnL, win rate cards
      OpenTrades.jsx       — Active positions table
      TradeHistory.jsx     — Closed trades table with PnL
      PriceTickerAll.jsx   — Live price grid (top coins)
      AIReasoningPanel.jsx — Claude's latest decision + reasoning
      MemoryStats.jsx      — Bot memory key-value viewer
      ModeToggle.jsx       — Paper / Live mode indicator
```

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/coinspot-trading-bot.git
cd coinspot-trading-bot
cp .env.example .env
# Edit .env with your API keys
```

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Configuration

| Variable | Default | Description |
|---|---|---|
| `COINSPOT_API_KEY` | — | CoinSpot API key |
| `COINSPOT_API_SECRET` | — | CoinSpot API secret |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `TRADING_MODE` | `paper` | `paper` or `live` |
| `PAPER_BALANCE` | `1000` | Starting AUD for paper mode |
| `BOT_INTERVAL_SECONDS` | `60` | How often the bot runs |

## Risk Disclaimer

This software is for **educational and research purposes only**. Cryptocurrency trading carries significant risk. The authors are not responsible for any financial losses. Always start with paper mode and test thoroughly before enabling live trading.

## License

MIT
