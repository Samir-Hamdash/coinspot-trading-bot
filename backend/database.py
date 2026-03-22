"""Persistent memory system — aiosqlite backend with JSON export."""
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Any

import aiosqlite

from config import BACKUP_PATH, DB_PATH

# ── Schema ─────────────────────────────────────────────────────────────────────

_CREATE_TABLES = """
PRAGMA journal_mode=WAL;

-- Price history: one row per coin per bot tick
CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    coin        TEXT    NOT NULL,
    price_aud   REAL    NOT NULL,
    volume      REAL,
    timestamp   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_coin_ts
    ON price_history (coin, timestamp DESC);

-- Every decision Claude makes (buy/sell/hold, with direction)
CREATE TABLE IF NOT EXISTS trade_decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    coin        TEXT,
    action      TEXT    NOT NULL,   -- 'buy' | 'sell' | 'hold'
    direction   TEXT,               -- 'long' | 'short' | NULL
    confidence  REAL,
    reasoning   TEXT,
    timestamp   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trade_decisions_ts
    ON trade_decisions (timestamp DESC);

-- Currently open positions
CREATE TABLE IF NOT EXISTS open_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    coin        TEXT    NOT NULL,
    direction   TEXT    NOT NULL,   -- 'long' | 'short'
    entry_price REAL    NOT NULL,
    quantity    REAL    NOT NULL,
    value_aud   REAL    NOT NULL,
    entry_time  TEXT    NOT NULL,
    mode        TEXT    NOT NULL    -- 'paper' | 'real'
);

-- Closed positions — full history
CREATE TABLE IF NOT EXISTS closed_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    coin        TEXT    NOT NULL,
    direction   TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    quantity    REAL    NOT NULL,
    value_aud   REAL    NOT NULL,
    entry_time  TEXT    NOT NULL,
    mode        TEXT    NOT NULL,
    exit_price  REAL    NOT NULL,
    exit_reason TEXT    NOT NULL,   -- 'stop_loss' | 'take_profit' | 'ai_decision'
    pnl_aud     REAL    NOT NULL,
    pnl_percent REAL    NOT NULL,
    exit_time   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_closed_trades_coin
    ON closed_trades (coin);
CREATE INDEX IF NOT EXISTS idx_closed_trades_exit_time
    ON closed_trades (exit_time DESC);

-- Portfolio snapshots (taken each bot tick)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    total_value_aud   REAL    NOT NULL,
    cash_aud          REAL    NOT NULL,
    holdings_value_aud REAL   NOT NULL,
    timestamp         TEXT    NOT NULL,
    mode              TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_ts
    ON portfolio_snapshots (timestamp DESC);

-- Key-value memory store (Claude's persistent notes)
CREATE TABLE IF NOT EXISTS memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT    NOT NULL UNIQUE,
    value       TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

-- Bot run log (one row per tick)
CREATE TABLE IF NOT EXISTS bot_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT    NOT NULL,
    mode        TEXT    NOT NULL,
    decision    TEXT,
    reasoning   TEXT,
    prices_json TEXT
);
"""


# ── Initialisation ────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Create all tables and indexes on first run; no-op on subsequent runs."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()


# ── Price history ─────────────────────────────────────────────────────────────

async def log_prices(prices: dict) -> None:
    """
    Insert one row per coin from a CoinSpot prices payload.
    Expected shape: {"prices": {"BTC": {"last": ..., "volume": ...}, ...}}
    """
    ts = datetime.utcnow().isoformat()
    rows = []
    for coin, data in prices.get("prices", {}).items():
        price = float(data.get("last") or data.get("bid") or 0)
        volume = float(data.get("volume") or 0)
        if price > 0:
            rows.append((coin, price, volume, ts))
    if not rows:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO price_history (coin, price_aud, volume, timestamp) VALUES (?,?,?,?)",
            rows,
        )
        await db.commit()


async def get_price_history(coin: str, limit: int = 500) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT coin, price_aud, volume, timestamp
               FROM price_history WHERE coin=? ORDER BY id DESC LIMIT ?""",
            (coin.upper(), limit),
        )
        return [dict(r) for r in await cur.fetchall()]


# ── Trade decisions ───────────────────────────────────────────────────────────

async def log_trade_decision(
    action: str,
    coin: str | None = None,
    direction: str | None = None,
    confidence: float | None = None,
    reasoning: str | None = None,
) -> int:
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO trade_decisions
               (coin, action, direction, confidence, reasoning, timestamp)
               VALUES (?,?,?,?,?,?)""",
            (coin, action, direction, confidence, reasoning, ts),
        )
        await db.commit()
        return cur.lastrowid


# ── Open trades ───────────────────────────────────────────────────────────────

async def open_trade(
    coin: str,
    direction: str,
    entry_price: float,
    quantity: float,
    value_aud: float,
    mode: str,
) -> int:
    entry_time = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO open_trades
               (coin, direction, entry_price, quantity, value_aud, entry_time, mode)
               VALUES (?,?,?,?,?,?,?)""",
            (coin.upper(), direction, entry_price, quantity, value_aud, entry_time, mode),
        )
        await db.commit()
        return cur.lastrowid


async def get_open_trades(mode: str | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if mode:
            cur = await db.execute(
                "SELECT * FROM open_trades WHERE mode=? ORDER BY entry_time DESC", (mode,)
            )
        else:
            cur = await db.execute("SELECT * FROM open_trades ORDER BY entry_time DESC")
        return [dict(r) for r in await cur.fetchall()]


async def close_trade(
    open_trade_id: int,
    exit_price: float,
    exit_reason: str,
) -> dict | None:
    """
    Move a row from open_trades → closed_trades, calculate PnL.
    Returns the closed_trade dict, or None if the open trade wasn't found.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM open_trades WHERE id=?", (open_trade_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        trade = dict(row)

    entry_price = trade["entry_price"]
    quantity = trade["quantity"]
    value_aud = trade["value_aud"]

    if trade["direction"] == "long":
        pnl_aud = (exit_price - entry_price) * quantity
    else:  # short
        pnl_aud = (entry_price - exit_price) * quantity

    pnl_percent = (pnl_aud / value_aud) * 100 if value_aud else 0.0
    exit_time = datetime.utcnow().isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO closed_trades
               (coin, direction, entry_price, quantity, value_aud, entry_time, mode,
                exit_price, exit_reason, pnl_aud, pnl_percent, exit_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade["coin"], trade["direction"], entry_price, quantity,
                value_aud, trade["entry_time"], trade["mode"],
                exit_price, exit_reason, pnl_aud, pnl_percent, exit_time,
            ),
        )
        closed_id = cur.lastrowid
        await db.execute("DELETE FROM open_trades WHERE id=?", (open_trade_id,))
        await db.commit()

    return {**trade, "exit_price": exit_price, "exit_reason": exit_reason,
            "pnl_aud": pnl_aud, "pnl_percent": pnl_percent, "exit_time": exit_time,
            "closed_id": closed_id}


async def get_closed_trades(limit: int = 100, coin: str | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if coin:
            cur = await db.execute(
                "SELECT * FROM closed_trades WHERE coin=? ORDER BY exit_time DESC LIMIT ?",
                (coin.upper(), limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM closed_trades ORDER BY exit_time DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in await cur.fetchall()]


# ── Portfolio snapshots ───────────────────────────────────────────────────────

async def snapshot_portfolio(
    total_value_aud: float,
    cash_aud: float,
    holdings_value_aud: float,
    mode: str,
) -> None:
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO portfolio_snapshots
               (total_value_aud, cash_aud, holdings_value_aud, timestamp, mode)
               VALUES (?,?,?,?,?)""",
            (total_value_aud, cash_aud, holdings_value_aud, ts, mode),
        )
        await db.commit()


async def get_portfolio_history(limit: int = 200, mode: str | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if mode:
            cur = await db.execute(
                """SELECT * FROM portfolio_snapshots WHERE mode=?
                   ORDER BY timestamp DESC LIMIT ?""", (mode, limit)
            )
        else:
            cur = await db.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in await cur.fetchall()]


# ── Key-value memory store ────────────────────────────────────────────────────

async def set_memory(key: str, value: Any) -> None:
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO memory (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE
               SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, json.dumps(value), ts),
        )
        await db.commit()


async def get_memory(key: str, default: Any = None) -> Any:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM memory WHERE key=?", (key,))
        row = await cur.fetchone()
        return json.loads(row[0]) if row else default


async def get_all_memory() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value, updated_at FROM memory")
        return {
            r["key"]: {"value": json.loads(r["value"]), "updated_at": r["updated_at"]}
            for r in await cur.fetchall()
        }


# ── Bot run log ───────────────────────────────────────────────────────────────

async def log_bot_run(mode: str, decision: str, reasoning: str, prices: dict) -> None:
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bot_runs (run_at, mode, decision, reasoning, prices_json)
               VALUES (?,?,?,?,?)""",
            (ts, mode, decision, reasoning, json.dumps(prices)),
        )
        await db.commit()


# ── Legacy shim (used by bot.py / main.py) ────────────────────────────────────

async def log_trade(
    coin: str,
    side: str,
    mode: str,
    price: float,
    quantity: float,
    aud_value: float,
    pnl: float | None = None,
    reason: str | None = None,
) -> int:
    """
    Compatibility wrapper: routes to open_trade or close_trade depending on side.
    For 'buy' it opens a new trade; for 'sell' it closes the newest matching open trade.
    """
    if side == "buy":
        return await open_trade(coin, "long", price, quantity, aud_value, mode)

    # side == "sell": find and close the most recent matching open trade
    open_positions = await get_open_trades(mode=mode)
    match = next((t for t in open_positions if t["coin"] == coin.upper()), None)
    if match:
        closed = await close_trade(
            match["id"],
            exit_price=price,
            exit_reason="ai_decision" if pnl is None else (
                "stop_loss" if pnl < 0 else "take_profit"
            ),
        )
        return closed["closed_id"] if closed else -1
    return -1


async def get_open_positions() -> list[dict]:
    """Compatibility shim for bot.py."""
    trades = await get_open_trades()
    # Re-map field names to match the original schema bot.py expects
    return [
        {
            "id": t["id"],
            "coin": t["coin"],
            "price": t["entry_price"],
            "quantity": t["quantity"],
            "aud_value": t["value_aud"],
            "reason": None,
            "mode": t["mode"],
            "direction": t["direction"],
            "entry_time": t["entry_time"],
        }
        for t in trades
    ]


async def get_trades(limit: int = 100) -> list[dict]:
    """Compatibility shim for bot.py / main.py — returns closed trades."""
    return await get_closed_trades(limit=limit)


# ── export_memory_to_json ─────────────────────────────────────────────────────

async def export_memory_to_json(output_dir: str = ".") -> str:
    """
    Dump every table to a single timestamped JSON file.
    Returns the path to the written file.
    """
    ts_label = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    filename = os.path.join(output_dir, f"memory_export_{ts_label}.json")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async def _fetch(sql: str, params: tuple = ()) -> list[dict]:
            cur = await db.execute(sql, params)
            return [dict(r) for r in await cur.fetchall()]

        payload = {
            "exported_at": datetime.utcnow().isoformat(),
            "price_history": await _fetch("SELECT * FROM price_history ORDER BY id"),
            "trade_decisions": await _fetch("SELECT * FROM trade_decisions ORDER BY id"),
            "open_trades": await _fetch("SELECT * FROM open_trades ORDER BY id"),
            "closed_trades": await _fetch("SELECT * FROM closed_trades ORDER BY id"),
            "portfolio_snapshots": await _fetch("SELECT * FROM portfolio_snapshots ORDER BY id"),
            "memory": await _fetch("SELECT * FROM memory ORDER BY key"),
            "bot_runs": await _fetch("SELECT * FROM bot_runs ORDER BY id"),
        }

    with open(filename, "w") as f:
        json.dump(payload, f, indent=2)

    return filename


# ── load_memory_summary ───────────────────────────────────────────────────────

async def load_memory_summary() -> dict:
    """
    Return a compact summary of trading history for Claude's context window.

    Includes:
    - Last 500 price points per coin (oldest-first for trend reading)
    - Last 100 closed trades
    - Win rate (overall and per coin)
    - Best / worst performing coins by average PnL %
    - Current open positions
    - Key-value memory store
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # ── Recent prices per coin (last 500 each) ────────────────────────────
        cur = await db.execute("SELECT DISTINCT coin FROM price_history")
        coins = [r[0] for r in await cur.fetchall()]

        price_data: dict[str, list] = {}
        for coin in coins:
            cur = await db.execute(
                """SELECT price_aud, volume, timestamp FROM price_history
                   WHERE coin=? ORDER BY id DESC LIMIT 500""",
                (coin,),
            )
            rows = [dict(r) for r in await cur.fetchall()]
            rows.reverse()  # oldest first
            price_data[coin] = rows

        # ── Last 100 closed trades ────────────────────────────────────────────
        cur = await db.execute(
            "SELECT * FROM closed_trades ORDER BY exit_time DESC LIMIT 100"
        )
        recent_trades = [dict(r) for r in await cur.fetchall()]

        # ── Win rate stats ────────────────────────────────────────────────────
        cur = await db.execute(
            "SELECT pnl_aud, pnl_percent, coin FROM closed_trades"
        )
        all_closed = [dict(r) for r in await cur.fetchall()]

        total = len(all_closed)
        wins = sum(1 for t in all_closed if t["pnl_aud"] > 0)
        win_rate = round((wins / total) * 100, 1) if total else None

        # Per-coin stats
        coin_pnls: dict[str, list[float]] = defaultdict(list)
        for t in all_closed:
            coin_pnls[t["coin"]].append(t["pnl_percent"])

        coin_stats = {
            coin: {
                "trades": len(pnls),
                "avg_pnl_pct": round(sum(pnls) / len(pnls), 2),
                "win_rate_pct": round(
                    sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1
                ),
            }
            for coin, pnls in coin_pnls.items()
        }

        ranked = sorted(coin_stats.items(), key=lambda x: x[1]["avg_pnl_pct"])
        worst_coins = [{"coin": c, **s} for c, s in ranked[:3]]
        best_coins = [{"coin": c, **s} for c, s in ranked[-3:][::-1]]

        # ── Open trades ───────────────────────────────────────────────────────
        cur = await db.execute("SELECT * FROM open_trades ORDER BY entry_time DESC")
        open_positions = [dict(r) for r in await cur.fetchall()]

        # ── Latest portfolio snapshot ─────────────────────────────────────────
        cur = await db.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
        )
        row = await cur.fetchone()
        latest_portfolio = dict(row) if row else None

        # ── Key-value memory ──────────────────────────────────────────────────
        cur = await db.execute("SELECT key, value, updated_at FROM memory")
        kv_memory = {
            r["key"]: {"value": json.loads(r["value"]), "updated_at": r["updated_at"]}
            for r in await cur.fetchall()
        }

        # ── Last 20 AI decisions ──────────────────────────────────────────────
        cur = await db.execute(
            "SELECT * FROM trade_decisions ORDER BY id DESC LIMIT 20"
        )
        recent_decisions = [dict(r) for r in await cur.fetchall()]

    return {
        "price_history": price_data,
        "recent_trades": recent_trades,
        "performance": {
            "total_closed_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate_pct": win_rate,
            "best_coins": best_coins,
            "worst_coins": worst_coins,
            "all_coin_stats": coin_stats,
        },
        "open_positions": open_positions,
        "latest_portfolio": latest_portfolio,
        "memory": kv_memory,
        "recent_decisions": recent_decisions,
    }


# ── JSON backup / restore (legacy support) ────────────────────────────────────

async def _backup_memory() -> None:
    data = await get_all_memory()
    with open(BACKUP_PATH, "w") as f:
        json.dump({"backup_at": datetime.utcnow().isoformat(), "memory": data}, f, indent=2)


async def restore_from_backup() -> None:
    """Load JSON backup into memory table if DB key-value store is empty."""
    if not os.path.exists(BACKUP_PATH):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM memory")
        count = (await cur.fetchone())[0]
    if count > 0:
        return  # don't overwrite existing memory
    with open(BACKUP_PATH) as f:
        data = json.load(f)
    for key, entry in data.get("memory", {}).items():
        await set_memory(key, entry["value"])
