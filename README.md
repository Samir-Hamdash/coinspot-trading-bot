# CoinSpot AI Trading Bot

An autonomous cryptocurrency trading bot that uses **Claude desktop** (via MCP) to analyse markets and execute trades on [CoinSpot](https://www.coinspot.com.au) — Australia's largest crypto exchange. Includes a real-time React dashboard with live WebSocket updates.

**No Anthropic API key required** — the AI brain runs inside your existing Claude desktop subscription.

---

## How it works

The bot runs a full cycle every 60 seconds:

1. **Fetches all CoinSpot coin prices** and stores them in SQLite
2. **Checks all open trades** against hard-coded risk limits (4% stop loss, 8% take profit) and auto-closes any that have breached them
3. **Publishes a market snapshot** to the shared database and waits for Claude desktop to respond
4. **Claude desktop** (via MCP) calls `analyse_market()`, analyses the data using its own intelligence, and calls `submit_trade_decisions()` with a JSON array of decisions
5. **Validates and executes** each decision against risk rules
6. **Saves a portfolio snapshot** and **broadcasts a live update** via WebSocket

Claude remembers everything across restarts — all price history, trades, and performance stats are persisted in `trading_bot.db`.

---

## Architecture

```
┌─────────────────────────────┐     stdio/MCP      ┌──────────────────────┐
│  backend/main.py            │ ◄────────────────── │  Claude Desktop App  │
│  (FastAPI + APScheduler)    │                     │                      │
│                             │  SQLite IPC         │  Calls tools:        │
│  bot.py  ──►  SQLite DB ────┼────────────────────►│  · analyse_market()  │
│  (60s tick)   trading_bot.db│◄────────────────────┼─ · submit_decisions()│
│                             │  decisions back      │  · get_portfolio()   │
└─────────────────────────────┘                     └──────────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  frontend/  (React + Vite)  │
│  Dashboard at :5173          │
└─────────────────────────────┘
```

**MCP IPC flow:**
- `bot.py` writes a market snapshot to `memory.pending_analysis` in SQLite and waits
- `mcp_server.py` (started by Claude desktop) reads the snapshot when Claude calls `analyse_market()`
- Claude submits decisions via `submit_trade_decisions()` → written to `memory.latest_decisions`
- `bot.py` picks up the decisions and executes trades

---

## Project structure

```
coinspot-trading-bot/
├── backend/
│   ├── main.py          FastAPI app + WebSocket server + REST API
│   ├── bot.py           Main bot loop (APScheduler, 60s interval)
│   ├── mcp_server.py    MCP server — tools Claude desktop calls
│   ├── coinspot.py      CoinSpot API v2 client (HMAC-SHA512)
│   ├── database.py      SQLite memory system
│   ├── risk.py          Hard-coded risk rules (stop loss, take profit, sizing)
│   ├── config.py        Environment variable loader
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/
│           ├── Dashboard.jsx
│           ├── PriceTickerAll.jsx
│           ├── OpenTrades.jsx
│           ├── AIReasoningPanel.jsx
│           ├── TradeHistory.jsx
│           ├── MemoryStats.jsx
│           └── ModeToggle.jsx
├── mcp_config.json      Paste into Claude desktop config
├── .env.example
├── .gitignore
└── README.md
```

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- [Claude desktop app](https://claude.ai/download) (any paid plan)
- A CoinSpot account (for API keys)

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/Samir-Hamdash/coinspot-trading-bot.git
cd coinspot-trading-bot
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your CoinSpot API keys:

```env
COINSPOT_API_KEY=your_key_here
COINSPOT_API_SECRET=your_secret_here
TRADING_MODE=paper
PAPER_BALANCE=1000
REAL_TRADING_CONFIRMED=false
```

No `ANTHROPIC_API_KEY` needed.

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

### 5. Configure Claude desktop to use the MCP server

**Windows** — open (or create) this file:
```
%APPDATA%\Claude\claude_desktop_config.json
```
i.e. `C:\Users\<you>\AppData\Roaming\Claude\claude_desktop_config.json`

**macOS** — open (or create):
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Paste in the contents of `mcp_config.json` from this repo, or merge the `mcpServers` section into your existing config:

```json
{
  "mcpServers": {
    "coinspot-trading-bot": {
      "command": "python",
      "args": ["backend/mcp_server.py"],
      "cwd": "C:\\Users\\shamd\\Downloads\\Coinspot_Ai_Trading_Bot"
    }
  }
}
```

> **Update the `cwd` path** to wherever you cloned the repo on your machine.
> On macOS/Linux use forward slashes: `"/home/you/coinspot-trading-bot"`

**Restart Claude desktop** after saving the config. You should see "coinspot-trading-bot" listed in the MCP servers panel (hammer icon in the chat input).

---

## Running the bot

### Start the backend

```bash
cd backend
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

uvicorn main:app --reload --port 8000
```

### Start the frontend (new terminal)

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) — the dashboard connects automatically.

---

## Using Claude desktop as the AI brain

Once the backend is running and Claude desktop has the MCP server connected, open Claude desktop and start a conversation:

### Run a single analysis cycle

```
Call analyse_market() to get the current market data, analyze it,
then call submit_trade_decisions() with your trading decisions.
```

### Run continuously (recommended)

```
You are the AI brain of my CoinSpot paper trading bot.

Every time the bot publishes new market data, call analyse_market()
to get it, analyze the prices and portfolio, then call
submit_trade_decisions() with your decisions as a JSON array.

Keep doing this — after each submit, wait a moment and then call
analyse_market() again to check for the next tick.

The bot runs every 60 seconds, so new data arrives each minute.
```

### Manual trades

You can also trade directly without waiting for the bot cycle:

```
Call get_portfolio() to see my current balance, then execute a
paper buy of BTC for AUD $200 using execute_paper_trade().
```

---

## MCP tools reference

| Tool | Description |
|---|---|
| `analyse_market()` | Returns current prices, portfolio, price history, and performance stats |
| `submit_trade_decisions(decisions_json)` | Submit a JSON array of buy/sell/hold decisions |
| `get_open_trades_tool()` | List open positions with P&L, stop-loss, and take-profit prices |
| `get_memory_stats()` | Win rate, best/worst coins, trade history length |
| `execute_paper_trade(coin, action, amount_aud)` | Manually execute a paper trade immediately |
| `get_portfolio()` | Current cash balance, holdings, and total value |

---

## REST API reference

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

## Hard-coded risk rules

These are defined as constants in `backend/risk.py` and **cannot be changed via config, API, or Claude**:

| Rule | Value | Description |
|---|---|---|
| **Stop Loss** | **4%** | Position auto-closed if price drops 4% below entry |
| **Take Profit** | **8%** | Position auto-closed if price rises 8% above entry |
| **Max Trade Size** | **20%** | No single trade can exceed 20% of total portfolio |
| **Max Open Positions** | 5 | Hard cap on concurrent trades |
| **Min Trade Size** | AUD $10 | CoinSpot minimum order |
| **Min Buy Confidence** | 60% | Claude must be ≥60% confident before a buy executes |

---

## How to get a CoinSpot API key

1. Log in to [coinspot.com.au](https://www.coinspot.com.au)
2. Go to **My Account → API Keys** (`https://www.coinspot.com.au/my/api`)
3. Click **Add Key** and set permissions:
   - Paper mode: **Read Only** is sufficient
   - Live trading: enable **Read** + **Trade**
4. Copy the **Key** and **Secret** into `.env`

> Never share your API secret. The `.env` file is in `.gitignore`.

---

## Enabling real trading (two-step confirmation)

Both gates must be active simultaneously:

**Step 1** — set `.env`:
```env
TRADING_MODE=real
REAL_TRADING_CONFIRMED=true
```

**Step 2** — click the **PAPER TRADING** banner in the dashboard and confirm in the modal.

> **Warning:** Real mode executes actual trades on CoinSpot using your funds. Always test in paper mode first.

---

## WebSocket events

| Event | Payload |
|---|---|
| `init` | Full state on connect |
| `bot_tick` | Full tick update: portfolio, decisions, trade counts |
| `trade_executed` | A trade was placed: coin, side, qty, price, P&L |
| `position_closed` | A risk exit occurred: coin, exit reason, P&L |
| `bot_error` | A tick failed |

---

## Risk disclaimer

This software is for **educational and research purposes only**. Cryptocurrency trading carries significant financial risk including the potential loss of your entire investment. The authors accept no responsibility for financial losses. Always start with paper mode and only trade amounts you can afford to lose completely.

---

## License

MIT
