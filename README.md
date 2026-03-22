# CoinSpot AI Trading Bot

An autonomous cryptocurrency trading bot that uses **Claude AI** (Anthropic) to analyse markets and execute trades on [CoinSpot](https://www.coinspot.com.au) — Australia's largest crypto exchange. Includes a real-time React dashboard with live WebSocket updates.

---

## What the bot does

Every 60 seconds the bot runs a full cycle:

1. **Fetches all CoinSpot coin prices** and stores them in a local SQLite database
2. **Loads its full memory** — price history, past trade outcomes, win rates, best/worst coins
3. **Checks all open trades** against hard-coded risk limits (4% stop loss, 8% take profit) and auto-closes any that have breached them
4. **Asks Claude AI** to analyse price trends across every coin and return a list of buy/sell/hold decisions with confidence scores and reasoning
5. **Validates every decision** against risk rules before executing
6. **Executes trades** — either simulated (paper mode) or real (live mode)
7. **Saves a portfolio snapshot** to the database
8. **Broadcasts a live update** to all connected dashboard clients via WebSocket

The bot remembers everything across restarts — all price history, trades, and AI decisions are persisted in `trading_bot.db`.

---

## Project structure

```
coinspot-trading-bot/
├── backend/
│   ├── main.py          FastAPI app + WebSocket server + REST API
│   ├── bot.py           Main bot loop (APScheduler, 60s interval)
│   ├── coinspot.py      CoinSpot API v2 client (HMAC-SHA512)
│   ├── claude_brain.py  Claude AI decision engine
│   ├── database.py      SQLite memory system (price history, trades, snapshots)
│   ├── risk.py          Hard-coded risk rules (stop loss, take profit, sizing)
│   ├── config.py        Environment variable loader
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/
│           ├── Dashboard.jsx        Balance, win rate, best coin stats
│           ├── PriceTickerAll.jsx   Live price grid with flash on change
│           ├── OpenTrades.jsx       Open positions with P&L, SL/TP prices
│           ├── AIReasoningPanel.jsx Last 5 AI decisions with confidence bars
│           ├── TradeHistory.jsx     Closed trades with outcome badges
│           ├── MemoryStats.jsx      Win rate, data age, best/worst coins
│           └── ModeToggle.jsx       Paper/Real mode indicator + confirmation
├── .env.example
├── .gitignore
└── README.md
```

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- A CoinSpot account (for API keys)
- An Anthropic account (for Claude API key)

---

## Setup instructions

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/coinspot-trading-bot.git
cd coinspot-trading-bot
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your keys (see sections below for how to get them):

```env
COINSPOT_API_KEY=your_key_here
COINSPOT_API_SECRET=your_secret_here
ANTHROPIC_API_KEY=your_anthropic_key_here
TRADING_MODE=paper
PAPER_BALANCE=1000
REAL_TRADING_CONFIRMED=false
```

### 3. Set up the Python backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Set up the React frontend

```bash
cd frontend
npm install
```

---

## How to get a CoinSpot API key

1. Log in to [coinspot.com.au](https://www.coinspot.com.au)
2. Go to **My Account → API Keys** (`https://www.coinspot.com.au/my/api`)
3. Click **Add Key**
4. Give it a name (e.g. "Trading Bot")
5. Set permissions:
   - For paper mode: **Read Only** is sufficient
   - For live trading: enable **Read** + **Trade** permissions
6. Copy the **Key** and **Secret** into your `.env` file

> **Important:** Never share your API secret. Keep your `.env` file out of version control (it is in `.gitignore` by default).

---

## How to get an Anthropic API key

1. Create an account at [console.anthropic.com](https://console.anthropic.com)
2. Go to **API Keys** in the left sidebar
3. Click **Create Key**
4. Copy the key (it starts with `sk-ant-...`) into your `.env` as `ANTHROPIC_API_KEY`

> The bot uses `claude-sonnet-4-6` by default. Check [Anthropic's pricing page](https://www.anthropic.com/pricing) for current rates. Each 60-second tick makes one API call.

---

## Running in paper mode (safe default)

Paper mode is the default. It simulates trades against a virtual AUD balance without touching real money.

**Start the backend:**

```bash
cd backend
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

uvicorn main:app --reload --port 8000
```

**Start the frontend (new terminal):**

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) — the dashboard will connect automatically.

The bot starts with **AUD $1,000 virtual balance** (configurable via `PAPER_BALANCE` in `.env`). Paper balance is persisted across restarts in the database.

---

## Enabling real trading (two-step confirmation)

Real trading is protected by two independent gates that **both** must be active:

### Step 1 — Set the `.env` flag

```env
TRADING_MODE=real
REAL_TRADING_CONFIRMED=true
```

Restart the backend after changing `.env`.

### Step 2 — Confirm in the dashboard UI

Once the server is running with both flags set:

1. Click the **PAPER TRADING** banner in the top-right of the dashboard
2. A confirmation modal will appear with a warning about real funds
3. Click **"Yes, use real funds"** to activate

If `REAL_TRADING_CONFIRMED=true` is not in `.env`, the UI button will be blocked with a clear error message — this prevents accidental activation.

> **Warning:** Real mode executes actual trades on CoinSpot using your funds. Always test thoroughly in paper mode first. Start with a small `PAPER_BALANCE` equivalent to what you're willing to risk.

---

## Hard-coded risk rules

These values are defined as constants in `backend/risk.py` and **cannot be overridden by any config file, environment variable, or API call**:

```python
# HARD-CODED — DO NOT MODIFY
STOP_LOSS_PERCENT = 4.0
TAKE_PROFIT_PERCENT = 8.0
MAX_TRADE_SIZE_PERCENT = 20.0
```

| Rule | Value | Description |
|---|---|---|
| **Stop Loss** | **4%** | Any position that drops 4% below entry price is automatically closed |
| **Take Profit** | **8%** | Any position that rises 8% above entry price is automatically closed |
| **Max Trade Size** | **20%** | No single trade can exceed 20% of your total portfolio value |
| **Max Open Positions** | 5 | Hard cap on concurrent open trades |
| **Min Trade Size** | AUD $10 | CoinSpot minimum order value |
| **Min Buy Confidence** | 60% | Claude must be at least 60% confident before a buy is executed |

Stop loss and take profit are checked every tick (every 60 seconds). Exits are executed immediately when triggered — they do not wait for the next Claude decision.

---

## How the AI memory works

The bot maintains a persistent memory in `trading_bot.db` (SQLite) with these tables:

| Table | Contents |
|---|---|
| `price_history` | Every coin's price saved each tick — used to identify trends |
| `trade_decisions` | Every AI decision (buy/sell/hold) with reasoning and confidence |
| `open_trades` | Currently open positions |
| `closed_trades` | All closed positions with entry/exit prices, P&L, and exit reason |
| `portfolio_snapshots` | Total portfolio value captured each tick |
| `memory` | Key-value store for Claude's persistent notes |

Each bot tick, Claude receives a **memory summary** containing:
- Last 500 price points per coin (oldest-first for trend reading)
- Last 100 closed trades with P&L outcomes
- Win rate and per-coin performance statistics
- Best and worst performing coins
- Current open positions
- Claude's own previous notes (key-value memory store)

Claude uses this data to **learn from past mistakes** — for example, if BTC has been consistently losing, Claude will factor that into its confidence score. The AI is explicitly instructed to prioritise capital preservation and to explain its reasoning referencing specific data points.

Memory survives restarts. A JSON backup is also written to `memory_backup.json` on every update.

To export the full memory to a downloadable JSON file, visit:
```
GET http://localhost:8000/memory/export
```

---

## API reference

| Method | Path | Description |
|---|---|---|
| GET | `/status` | Bot status, uptime, tick count |
| GET | `/portfolio` | Current holdings with live P&L |
| GET | `/trades/open` | Open positions with SL/TP prices |
| GET | `/trades/history` | Closed trades with outcome badges |
| GET | `/memory/stats` | Win rate, best/worst coins, data age |
| GET | `/memory/export` | Download full DB as JSON |
| POST | `/bot/start` | Resume the scheduler |
| POST | `/bot/stop` | Pause the scheduler |
| POST | `/bot/trigger` | Fire one tick immediately |
| POST | `/mode/paper` | Switch to paper mode |
| POST | `/mode/real` | Switch to real mode (requires `{"confirm": true}` + `.env` flag) |
| WS | `/ws` | Live updates stream |

---

## WebSocket events

All dashboard components receive live updates via WebSocket at `ws://localhost:8000/ws`.

| Event | Payload |
|---|---|
| `init` | Full state on connect: prices, open trades, decisions, bot status |
| `bot_tick` | Full tick update: portfolio, decisions, trade counts |
| `trade_executed` | A trade was placed: coin, side, qty, price, P&L |
| `position_closed` | A risk exit occurred: coin, exit reason, P&L |
| `bot_error` | A tick failed (e.g. price fetch error) |

---

## Risk disclaimer

This software is for **educational and research purposes only**. Cryptocurrency trading carries significant financial risk including the potential loss of your entire investment. The authors accept no responsibility for financial losses. Always start with paper mode, backtest thoroughly, and only trade amounts you can afford to lose completely.

---

## License

MIT
