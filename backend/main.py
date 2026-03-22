"""FastAPI app + WebSocket server."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import bot
from bot import bot_tick, set_broadcast_callback
from coinspot import get_latest_prices
from config import BOT_INTERVAL_SECONDS, TRADING_MODE
from database import get_all_memory, get_open_positions, get_trades, init_db, restore_from_backup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger(__name__)

# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


manager = ConnectionManager()


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await restore_from_backup()
    set_broadcast_callback(manager.broadcast)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(bot_tick, "interval", seconds=BOT_INTERVAL_SECONDS, id="bot_loop")
    scheduler.start()
    log.info("Bot scheduler started (interval=%ds, mode=%s)", BOT_INTERVAL_SECONDS, TRADING_MODE)

    # Run first tick immediately
    asyncio.create_task(bot_tick())

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(title="CoinSpot AI Trading Bot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": TRADING_MODE}


@app.get("/api/prices")
async def prices():
    return await get_latest_prices()


@app.get("/api/trades")
async def trades(limit: int = 100):
    return await get_trades(limit)


@app.get("/api/positions")
async def positions():
    return await get_open_positions()


@app.get("/api/memory")
async def memory():
    return await get_all_memory()


@app.get("/api/decision")
async def decision():
    return bot.get_last_decision()


@app.post("/api/bot/trigger")
async def trigger_tick():
    """Manually trigger a bot cycle."""
    asyncio.create_task(bot_tick())
    return {"status": "triggered"}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    log.info("WS client connected. Total: %d", len(manager.active))
    try:
        while True:
            # Keep connection alive; bot pushes updates via broadcast
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        log.info("WS client disconnected. Total: %d", len(manager.active))
