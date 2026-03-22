"""SQLite + JSON backup memory system."""
import json
import os
from datetime import datetime
from typing import Any

import aiosqlite

from config import BACKUP_PATH, DB_PATH

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    coin        TEXT    NOT NULL,
    side        TEXT    NOT NULL,        -- 'buy' | 'sell'
    mode        TEXT    NOT NULL,        -- 'paper' | 'live'
    price       REAL    NOT NULL,
    quantity    REAL    NOT NULL,
    aud_value   REAL    NOT NULL,
    pnl         REAL,                   -- filled on sell
    reason      TEXT,                   -- Claude's reasoning
    timestamp   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT    NOT NULL UNIQUE,
    value       TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT    NOT NULL,
    mode        TEXT    NOT NULL,
    decision    TEXT,
    reasoning   TEXT,
    prices_json TEXT
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES)
        await db.commit()


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
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO trades
               (coin, side, mode, price, quantity, aud_value, pnl, reason, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (coin, side, mode, price, quantity, aud_value, pnl, reason, ts),
        )
        await db.commit()
        return cur.lastrowid


async def log_bot_run(
    mode: str,
    decision: str,
    reasoning: str,
    prices: dict,
) -> None:
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bot_runs (run_at, mode, decision, reasoning, prices_json)
               VALUES (?,?,?,?,?)""",
            (ts, mode, decision, reasoning, json.dumps(prices)),
        )
        await db.commit()


async def get_trades(limit: int = 100) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_open_positions() -> list[dict]:
    """Returns buys that don't yet have a matching sell (simplified)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM trades WHERE side='buy' AND pnl IS NULL ORDER BY id DESC"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def set_memory(key: str, value: Any) -> None:
    ts = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO memory (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, json.dumps(value), ts),
        )
        await db.commit()
    await _backup_memory()


async def get_memory(key: str, default: Any = None) -> Any:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM memory WHERE key=?", (key,))
        row = await cur.fetchone()
        if row:
            return json.loads(row[0])
        return default


async def get_all_memory() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value, updated_at FROM memory")
        rows = await cur.fetchall()
        return {r["key"]: {"value": json.loads(r["value"]), "updated_at": r["updated_at"]} for r in rows}


async def _backup_memory() -> None:
    """Persist memory table to JSON file as a secondary backup."""
    data = await get_all_memory()
    with open(BACKUP_PATH, "w") as f:
        json.dump({"backup_at": datetime.utcnow().isoformat(), "memory": data}, f, indent=2)


async def restore_from_backup() -> None:
    """Load JSON backup into memory table if DB is empty."""
    if not os.path.exists(BACKUP_PATH):
        return
    with open(BACKUP_PATH) as f:
        data = json.load(f)
    for key, entry in data.get("memory", {}).items():
        await set_memory(key, entry["value"])
