"""FastAPI app — REST API + WebSocket server + APScheduler bot loop."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import bot
from bot import bot_tick, initialise_bot, set_broadcast_callback
from coinspot import get_latest_prices
from config import BOT_INTERVAL_SECONDS, REAL_TRADING_CONFIRMED, TRADING_MODE
from database import (
    export_memory_to_json,
    get_all_memory,
    get_closed_trades,
    get_open_positions,
    get_open_trades,
    get_portfolio_history,
    get_price_history,
    load_memory_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

_start_time = datetime.now(timezone.utc)


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        log.info("WS connected (total=%d)", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        log.info("WS disconnected (total=%d)", len(self.active))

    async def broadcast(self, data: dict) -> None:
        if not self.active:
            return
        message = json.dumps(data, default=str)
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self.active:
                self.active.remove(ws)

    def client_count(self) -> int:
        return len(self.active)


manager = ConnectionManager()
_scheduler: AsyncIOScheduler | None = None


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler

    await initialise_bot()
    set_broadcast_callback(manager.broadcast)

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(bot_tick, "interval", seconds=BOT_INTERVAL_SECONDS, id="bot_loop")
    _scheduler.start()
    log.info("Scheduler started (interval=%ds, mode=%s, real_enabled=%s)",
             BOT_INTERVAL_SECONDS, TRADING_MODE, REAL_TRADING_CONFIRMED)

    # Fire first tick immediately without blocking startup
    asyncio.create_task(bot_tick())

    yield

    _scheduler.shutdown(wait=False)
    log.info("Scheduler stopped")


app = FastAPI(
    title="CoinSpot AI Trading Bot",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _uptime_seconds() -> float:
    return (datetime.now(timezone.utc) - _start_time).total_seconds()


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    """Bot health, mode, uptime, and trade counts."""
    open_trades = await get_open_trades()
    closed_trades = await get_closed_trades(limit=10_000)
    return {
        "status": "running" if bot.is_running() else "stopped",
        "scheduler_running": _scheduler.running if _scheduler else False,
        "mode": TRADING_MODE,
        "real_trading_enabled": bot._real_trading_enabled(),
        "real_trading_confirmed": REAL_TRADING_CONFIRMED,
        "uptime_seconds": round(_uptime_seconds()),
        "tick_count": bot.get_tick_count(),
        "last_tick_at": bot.get_last_tick_at().isoformat() if bot.get_last_tick_at() else None,
        "websocket_clients": manager.client_count(),
        "open_trade_count": len(open_trades),
        "closed_trade_count": len(closed_trades),
    }


# ── Portfolio ─────────────────────────────────────────────────────────────────

@app.get("/portfolio")
async def portfolio():
    """Current holdings with AUD values and live P&L estimates."""
    open_trades = await get_open_trades()
    prices = bot.get_last_prices()
    price_map = prices.get("prices", {})

    enriched = []
    for trade in open_trades:
        coin = trade["coin"]
        entry = float(trade["entry_price"])
        qty = float(trade["quantity"])
        value_aud = float(trade["value_aud"])

        price_data = price_map.get(coin) or price_map.get(coin.lower(), {})
        current = float(price_data.get("last") or price_data.get("bid") or entry)

        if trade.get("direction", "long") == "long":
            pnl_aud = (current - entry) * qty
        else:
            pnl_aud = (entry - current) * qty
        pnl_pct = (pnl_aud / value_aud * 100) if value_aud else 0

        from risk import STOP_LOSS_PERCENT, TAKE_PROFIT_PERCENT
        sl_price = round(entry * (1 - STOP_LOSS_PERCENT / 100), 6)
        tp_price = round(entry * (1 + TAKE_PROFIT_PERCENT / 100), 6)

        enriched.append({
            **trade,
            "current_price": current,
            "pnl_aud": round(pnl_aud, 2),
            "pnl_percent": round(pnl_pct, 4),
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
        })

    holdings_value = sum(t["pnl_aud"] + float(t["value_aud"]) for t in enriched)
    cash = bot._paper_balance if not bot._real_trading_enabled() else 0.0

    return {
        "cash_aud": round(cash, 2),
        "holdings_value_aud": round(holdings_value, 2),
        "total_value_aud": round(cash + holdings_value, 2),
        "open_trades": enriched,
        "mode": TRADING_MODE,
    }


# ── Open trades ───────────────────────────────────────────────────────────────

@app.get("/trades/open")
async def trades_open():
    """All open trades with live P&L, stop-loss, and take-profit prices."""
    # Reuse portfolio endpoint logic
    return (await portfolio())["open_trades"]


# ── Trade history ─────────────────────────────────────────────────────────────

@app.get("/trades/history")
async def trades_history(limit: int = 100, coin: str | None = None):
    """Closed trades with exit reason badges."""
    trades = await get_closed_trades(limit=limit, coin=coin)
    # Normalise exit_reason to a display label
    label_map = {
        "stop_loss": "STOP LOSS",
        "take_profit": "TAKE PROFIT",
        "ai_decision": "AI CLOSE",
    }
    for t in trades:
        t["exit_label"] = label_map.get(t.get("exit_reason", ""), t.get("exit_reason", ""))
    return trades


# ── Memory / stats ────────────────────────────────────────────────────────────

@app.get("/memory/stats")
async def memory_stats():
    """Aggregated stats: trade count, win rate, best/worst coins, data age."""
    summary = await load_memory_summary()
    perf = summary.get("performance", {})

    # Calculate data history length in days
    price_history = summary.get("price_history", {})
    oldest_ts: str | None = None
    for points in price_history.values():
        if points:
            ts = points[0].get("timestamp")
            if ts and (oldest_ts is None or ts < oldest_ts):
                oldest_ts = ts

    history_days: float | None = None
    if oldest_ts:
        try:
            oldest_dt = datetime.fromisoformat(oldest_ts.replace("Z", "+00:00"))
            history_days = round((datetime.now(timezone.utc) - oldest_dt).total_seconds() / 86400, 1)
        except Exception:
            pass

    return {
        "total_trades": perf.get("total_closed_trades", 0),
        "wins": perf.get("wins", 0),
        "losses": perf.get("losses", 0),
        "win_rate_pct": perf.get("win_rate_pct"),
        "best_coins": perf.get("best_coins", []),
        "worst_coins": perf.get("worst_coins", []),
        "all_coin_stats": perf.get("all_coin_stats", {}),
        "data_history_days": history_days,
        "price_history_coins": list(price_history.keys()),
        "open_positions": len(summary.get("open_positions", [])),
    }


@app.get("/memory/export")
async def memory_export():
    """Dump all tables to a timestamped JSON file and stream it as a download."""
    path = await export_memory_to_json(output_dir=".")
    filename = os.path.basename(path)
    return FileResponse(path, media_type="application/json", filename=filename)


# ── Bot control ───────────────────────────────────────────────────────────────

@app.post("/bot/start")
async def bot_start():
    """Resume the scheduler if it was stopped."""
    if _scheduler is None:
        raise HTTPException(503, "Scheduler not initialised")
    if _scheduler.running:
        return {"status": "already_running"}
    _scheduler.start()
    log.info("Scheduler started via API")
    return {"status": "started"}


@app.post("/bot/stop")
async def bot_stop():
    """Pause the scheduler (does not reset state)."""
    if _scheduler is None:
        raise HTTPException(503, "Scheduler not initialised")
    if not _scheduler.running:
        return {"status": "already_stopped"}
    _scheduler.pause()
    log.info("Scheduler paused via API")
    return {"status": "stopped"}


@app.post("/bot/trigger")
async def bot_trigger():
    """Manually fire one bot tick immediately."""
    asyncio.create_task(bot_tick())
    return {"status": "triggered", "tick": bot.get_tick_count() + 1}


# ── Mode switching ────────────────────────────────────────────────────────────

@app.post("/mode/paper")
async def switch_to_paper():
    """Switch to paper trading mode (no restart required)."""
    import config as _cfg
    _cfg.TRADING_MODE = "paper"          # type: ignore[attr-defined]
    log.info("Switched to PAPER mode via API")
    return {"mode": "paper", "message": "Now in paper trading mode. Restart for .env changes to persist."}


@app.post("/mode/real")
async def switch_to_real(body: dict = Body(...)):
    """
    Switch to real trading mode.
    Requires body: {"confirm": true}
    Also requires REAL_TRADING_CONFIRMED=true in .env.
    """
    if not body.get("confirm"):
        raise HTTPException(
            400,
            detail="Must send {'confirm': true} to enable real trading.",
        )
    if not REAL_TRADING_CONFIRMED:
        raise HTTPException(
            403,
            detail=(
                "REAL_TRADING_CONFIRMED is not set to true in .env. "
                "Add REAL_TRADING_CONFIRMED=true to your .env file and restart the server."
            ),
        )
    import config as _cfg
    _cfg.TRADING_MODE = "real"           # type: ignore[attr-defined]
    log.warning("Switched to REAL trading mode via API")
    return {
        "mode": "real",
        "message": "Now in REAL trading mode. Trades will use real funds.",
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    # Send current state immediately on connect so the dashboard doesn't wait up to 60s
    try:
        open_trades = await get_open_trades()
        prices = bot.get_last_prices()
        price_map = prices.get("prices", {})

        await websocket.send_text(json.dumps({
            "event": "init",
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": {
                "mode": TRADING_MODE,
                "real_enabled": bot._real_trading_enabled(),
                "prices": price_map,
                "open_trades": open_trades,
                "decisions": bot.get_last_decisions(),
                "bot_status": {
                    "tick_count": bot.get_tick_count(),
                    "last_tick_at": bot.get_last_tick_at().isoformat() if bot.get_last_tick_at() else None,
                    "running": bot.is_running(),
                },
            },
        }, default=str))
    except Exception as exc:
        log.warning("Failed to send init frame: %s", exc)

    try:
        while True:
            await websocket.receive_text()   # keep-alive; bot pushes updates
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── Legacy / convenience aliases ─────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": TRADING_MODE}


@app.get("/api/prices")
async def prices_legacy():
    return await get_latest_prices()


@app.get("/api/prices/history/{coin}")
async def price_history(coin: str, limit: int = 500):
    return await get_price_history(coin, limit=limit)


@app.get("/api/portfolio/history")
async def portfolio_history_legacy(limit: int = 200, mode: str | None = None):
    return await get_portfolio_history(limit=limit, mode=mode)


@app.get("/api/decisions")
async def decisions():
    return bot.get_last_decisions()


@app.get("/api/memory")
async def memory_kv():
    return await get_all_memory()


# Aliases used by frontend components
@app.get("/api/positions")
async def positions_alias():
    return await get_open_trades()


@app.get("/api/decision")
async def decision_alias():
    decisions = bot.get_last_decisions()
    if not decisions:
        return {"decision": "hold", "coin": None, "confidence": 0, "reasoning": "No decisions yet.", "trend": "neutral"}
    best = max(decisions, key=lambda d: d.get("confidence", 0))
    return {**best, "confidence": best.get("confidence", 0) / 100.0}


@app.get("/api/trades")
async def trades_alias(limit: int = 100, coin: str | None = None):
    return await get_closed_trades(limit=limit, coin=coin)
