"""
Main bot loop — runs every 60 seconds via APScheduler.

Startup sequence
----------------
1. init_db() / restore_from_backup()
2. Load persisted paper_cash_aud from memory table (survives restarts)
3. APScheduler fires bot_tick() every BOT_INTERVAL_SECONDS

Tick sequence
-------------
1. Fetch all CoinSpot prices  →  save to price_history
2. Load full memory summary from DB
3. Resolve current portfolio (paper balance from memory, or live from API)
4. risk.check_open_trades()  →  auto-close stop-loss / take-profit hits
5. claude_brain.analyse_market()  →  list of AI decisions
6. For each non-hold decision: validate → execute (paper or real)
7. Save new open trades to open_trades table
8. Portfolio snapshot
9. Persist paper_cash_aud to memory table
10. Broadcast full state update via WebSocket
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from mcp_server import request_mcp_analysis
from coinspot import get_latest_prices, get_my_balances, place_buy_order, place_sell_order
from config import (
    BOT_INTERVAL_SECONDS,
    PAPER_BALANCE,
    REAL_TRADING_CONFIRMED,
    TRADING_MODE,
)
from database import (
    close_trade,
    get_memory,
    get_open_trades,
    init_db,
    load_memory_summary,
    log_bot_run,
    log_prices,
    open_trade,
    restore_from_backup,
    set_memory,
    snapshot_portfolio,
)
from risk import calculate_trade_size, check_open_trades, validate_trade

log = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────

_paper_balance: float = PAPER_BALANCE   # overwritten by _load_state() on startup
_last_decisions: list[dict] = []        # most recent Claude decisions
_last_prices: dict = {}                 # most recent price payload
_last_tick_at: datetime | None = None
_tick_count: int = 0
_is_running: bool = False
_broadcast_callback = None              # set by main.py


# ── Real-trading guard ────────────────────────────────────────────────────────

def _real_trading_enabled() -> bool:
    """Both TRADING_MODE=real and REAL_TRADING_CONFIRMED=true must be set."""
    return TRADING_MODE == "real" and REAL_TRADING_CONFIRMED


# ── Helpers ───────────────────────────────────────────────────────────────────

def set_broadcast_callback(cb) -> None:
    global _broadcast_callback
    _broadcast_callback = cb


def get_last_decisions() -> list[dict]:
    return _last_decisions


def get_last_prices() -> dict:
    return _last_prices


def get_tick_count() -> int:
    return _tick_count


def get_last_tick_at() -> datetime | None:
    return _last_tick_at


def is_running() -> bool:
    return _is_running


async def _broadcast(event: str, data: dict) -> None:
    if _broadcast_callback:
        try:
            await _broadcast_callback({"event": event, "data": data, "ts": datetime.now(timezone.utc).isoformat()})
        except Exception as exc:
            log.warning("Broadcast error: %s", exc)


async def _get_cash_balance() -> float:
    """Return available AUD cash. Uses DB for paper, CoinSpot API for real."""
    global _paper_balance
    if not _real_trading_enabled():
        return _paper_balance
    result = await get_my_balances()
    if result is None:
        log.error("Failed to fetch live balance — using 0")
        return 0.0
    return result.get("aud", 0.0)


async def _get_portfolio(open_trades: list[dict], cash_aud: float) -> dict:
    open_vals = sum(float(t.get("value_aud", 0)) for t in open_trades)
    return {
        "cash_aud": cash_aud,
        "holdings_value_aud": open_vals,
        "total_value_aud": cash_aud + open_vals,
        "open_trades": open_trades,
    }


# ── Startup ───────────────────────────────────────────────────────────────────

async def initialise_bot() -> None:
    """
    Must be awaited once before the scheduler starts.
    Initialises the DB and reloads persisted state.
    """
    global _paper_balance, _is_running

    await init_db()
    await restore_from_backup()

    # Reload paper balance from last known value (survives restart)
    saved_balance = await get_memory("paper_cash_aud")
    if saved_balance is not None:
        _paper_balance = float(saved_balance)
        log.info("Restored paper balance: AUD %.2f", _paper_balance)
    else:
        _paper_balance = PAPER_BALANCE
        await set_memory("paper_cash_aud", _paper_balance)
        log.info("Initialised paper balance: AUD %.2f", _paper_balance)

    if TRADING_MODE == "real" and not REAL_TRADING_CONFIRMED:
        log.warning(
            "TRADING_MODE=real but REAL_TRADING_CONFIRMED is not true — "
            "bot will run in PAPER mode until REAL_TRADING_CONFIRMED=true is set in .env"
        )

    _is_running = True
    log.info(
        "Bot initialised. mode=%s real_enabled=%s interval=%ds",
        TRADING_MODE, _real_trading_enabled(), BOT_INTERVAL_SECONDS,
    )


# ── Risk exit processing ──────────────────────────────────────────────────────

async def _process_risk_exits(open_trades: list[dict], prices: dict) -> list[dict]:
    """
    Close any trades that have breached stop-loss or take-profit.
    Returns the updated open_trades list after exits are processed.
    """
    global _paper_balance

    exits = check_open_trades(open_trades, prices)
    if not exits:
        return open_trades

    for exit_trade in exits:
        trade_id = exit_trade["id"]
        coin = exit_trade["coin"]
        current_price = exit_trade["current_price"]
        qty = float(exit_trade["quantity"])
        aud_val = qty * current_price
        exit_reason = exit_trade["exit_reason"]

        log.info("Auto-exit %s [%s]: %s", coin, exit_reason, exit_trade["message"])

        if not _real_trading_enabled():
            # Paper: close in DB and credit cash
            closed = await close_trade(trade_id, current_price, exit_reason)
            if closed:
                _paper_balance += aud_val
                await set_memory("paper_cash_aud", _paper_balance)
                await _broadcast("position_closed", {
                    "coin": coin,
                    "exit_reason": exit_reason,
                    "pnl_aud": exit_trade["pnl_aud"],
                    "pnl_percent": exit_trade["pnl_percent"],
                    "message": exit_trade["message"],
                })
        else:
            # Real: execute sell on exchange
            result = await place_sell_order(coin, qty)
            if result is None:
                log.error("Exchange sell for %s failed — position remains open", coin)
                continue
            await close_trade(trade_id, current_price, exit_reason)
            await _broadcast("position_closed", {
                "coin": coin,
                "exit_reason": exit_reason,
                "pnl_aud": exit_trade["pnl_aud"],
                "pnl_percent": exit_trade["pnl_percent"],
            })

    # Reload open trades after exits
    return await get_open_trades()


# ── Trade execution ───────────────────────────────────────────────────────────

async def _execute_buy(
    decision: dict,
    prices: dict,
    portfolio: dict,
) -> bool:
    """Execute a buy decision. Returns True if trade was placed."""
    global _paper_balance

    coin = decision["coin"]
    _pd = prices.get("prices", {})
    price_data = _pd.get(coin) or _pd.get(coin.lower(), {})
    ask_price = float(price_data.get("ask") or price_data.get("last") or 0)

    if ask_price <= 0:
        log.warning("No ask price for %s — skipping buy", coin)
        return False

    sizing = calculate_trade_size(portfolio["total_value_aud"])
    if not sizing["ok"]:
        log.warning("Position sizing rejected for %s: %s", coin, sizing["reason"])
        return False

    # Can't spend more cash than we have
    aud_spend = min(sizing["max_aud"], portfolio["cash_aud"])
    qty = round(aud_spend / ask_price, 8)

    validation = validate_trade(
        {
            "coin": coin, "side": "buy", "direction": "long",
            "aud_value": aud_spend, "quantity": qty,
        },
        portfolio,
    )
    if not validation["ok"]:
        log.warning("Buy validation failed for %s: %s", coin, validation["reason"])
        return False

    if not _real_trading_enabled():
        # Paper trade
        trade_id = await open_trade(
            coin=coin, direction="long",
            entry_price=ask_price, quantity=qty,
            value_aud=aud_spend, mode="paper",
        )
        _paper_balance -= aud_spend
        await set_memory("paper_cash_aud", _paper_balance)
        log.info(
            "PAPER BUY  %s  qty=%.8f  price=%.4f  AUD=%.2f  [trade_id=%d]",
            coin, qty, ask_price, aud_spend, trade_id,
        )
        await _broadcast("trade_executed", {
            "side": "buy", "coin": coin, "qty": qty,
            "price": ask_price, "aud": aud_spend, "mode": "paper",
        })
    else:
        # Real trade
        result = await place_buy_order(coin, aud_spend)
        if result is None:
            log.error("Exchange buy for %s failed", coin)
            return False
        # Record the open trade at the price we expected (exchange fill may differ slightly)
        await open_trade(
            coin=coin, direction="long",
            entry_price=ask_price, quantity=qty,
            value_aud=aud_spend, mode="real",
        )
        await _broadcast("trade_executed", {
            "side": "buy", "coin": coin, "qty": qty,
            "price": ask_price, "aud": aud_spend, "mode": "real",
        })

    return True


async def _execute_sell(
    decision: dict,
    prices: dict,
    portfolio: dict,
) -> bool:
    """Close an existing position based on a sell decision. Returns True if trade was placed."""
    global _paper_balance

    coin = decision["coin"]
    open_trades = portfolio["open_trades"]
    position = next((t for t in open_trades if t["coin"] == coin), None)

    if position is None:
        log.warning("Sell signal for %s but no open position found", coin)
        return False

    _pd = prices.get("prices", {})
    price_data = _pd.get(coin) or _pd.get(coin.lower(), {})
    bid_price = float(price_data.get("bid") or price_data.get("last") or position["entry_price"])
    qty = float(position["quantity"])
    aud_val = qty * bid_price

    validation = validate_trade(
        {
            "coin": coin, "side": "sell",
            "direction": position.get("direction", "long"),
            "aud_value": aud_val, "quantity": qty,
        },
        portfolio,
    )
    if not validation["ok"]:
        log.warning("Sell validation failed for %s: %s", coin, validation["reason"])
        return False

    if not _real_trading_enabled():
        closed = await close_trade(position["id"], bid_price, "ai_decision")
        if closed is None:
            log.error("DB close_trade failed for position %d", position["id"])
            return False
        _paper_balance += aud_val
        await set_memory("paper_cash_aud", _paper_balance)
        log.info(
            "PAPER SELL %s  qty=%.8f  price=%.4f  pnl=AUD %.2f (%.2f%%)",
            coin, qty, bid_price, closed["pnl_aud"], closed["pnl_percent"],
        )
        await _broadcast("trade_executed", {
            "side": "sell", "coin": coin, "qty": qty,
            "price": bid_price, "pnl_aud": closed["pnl_aud"],
            "pnl_percent": closed["pnl_percent"], "mode": "paper",
        })
    else:
        result = await place_sell_order(coin, qty)
        if result is None:
            log.error("Exchange sell for %s failed", coin)
            return False
        closed = await close_trade(position["id"], bid_price, "ai_decision")
        await _broadcast("trade_executed", {
            "side": "sell", "coin": coin, "qty": qty,
            "price": bid_price,
            "pnl_aud": closed["pnl_aud"] if closed else None,
            "mode": "real",
        })

    return True


# ── Main tick ─────────────────────────────────────────────────────────────────

async def bot_tick() -> None:
    """Single bot cycle. Safe to call manually for testing."""
    global _last_decisions, _last_prices, _last_tick_at, _tick_count, _paper_balance

    tick_start = datetime.now(timezone.utc)
    log.info("── Bot tick #%d  %s  mode=%s ──", _tick_count + 1, tick_start.isoformat(), TRADING_MODE)

    # ── Step 1: Fetch prices ──────────────────────────────────────────────────
    prices = await get_latest_prices()
    if prices is None:
        log.error("Price fetch failed — aborting tick")
        await _broadcast("bot_error", {"message": "Price fetch failed", "ts": tick_start.isoformat()})
        return

    _last_prices = prices
    await log_prices(prices)

    # ── Step 2: Load memory summary ───────────────────────────────────────────
    memory_summary = await load_memory_summary()

    # ── Step 3: Resolve portfolio ─────────────────────────────────────────────
    cash = await _get_cash_balance()
    open_trades = await get_open_trades()
    portfolio = await _get_portfolio(open_trades, cash)

    # ── Step 4: Risk exits ────────────────────────────────────────────────────
    open_trades = await _process_risk_exits(open_trades, prices)
    # Refresh portfolio after exits (balance may have changed)
    cash = await _get_cash_balance()
    portfolio = await _get_portfolio(open_trades, cash)

    # ── Step 5: Claude analysis ───────────────────────────────────────────────
    decisions = await request_mcp_analysis(prices, portfolio, memory_summary)
    _last_decisions = decisions

    # ── Step 6: Execute non-hold decisions ────────────────────────────────────
    buys_placed = 0
    sells_placed = 0

    for decision in decisions:
        if decision["action"] == "hold":
            continue

        # Refresh open trades and portfolio before each trade so
        # each decision sees the latest state (previous buys reduce cash, etc.)
        open_trades = await get_open_trades()
        cash = await _get_cash_balance()
        portfolio = await _get_portfolio(open_trades, cash)

        if decision["action"] == "buy":
            placed = await _execute_buy(decision, prices, portfolio)
            if placed:
                buys_placed += 1
        elif decision["action"] == "sell":
            placed = await _execute_sell(decision, prices, portfolio)
            if placed:
                sells_placed += 1

    # ── Step 7 + 8: Final state + snapshot ───────────────────────────────────
    open_trades = await get_open_trades()
    cash = await _get_cash_balance()
    open_vals = sum(float(t.get("value_aud", 0)) for t in open_trades)
    total_value = cash + open_vals

    await snapshot_portfolio(
        total_value_aud=total_value,
        cash_aud=cash,
        holdings_value_aud=open_vals,
        mode="paper" if not _real_trading_enabled() else "real",
    )

    # ── Step 9: Persist paper balance ─────────────────────────────────────────
    if not _real_trading_enabled():
        await set_memory("paper_cash_aud", _paper_balance)

    # ── Step 10: Log run + broadcast ─────────────────────────────────────────
    primary_action = "hold"
    primary_coin = None
    if decisions:
        actionable = [d for d in decisions if d["action"] != "hold"]
        if actionable:
            best = max(actionable, key=lambda d: d["confidence"])
            primary_action = best["action"]
            primary_coin = best["coin"]

    await log_bot_run(
        mode="paper" if not _real_trading_enabled() else "real",
        decision=primary_action,
        reasoning=f"{len(decisions)} decisions; {buys_placed} buys, {sells_placed} sells placed",
        prices=prices,
    )

    _last_tick_at = tick_start
    _tick_count += 1

    elapsed_ms = (datetime.now(timezone.utc) - tick_start).total_seconds() * 1000
    log.info(
        "Tick complete: %d decisions, %d buys, %d sells placed  (%.0fms)",
        len(decisions), buys_placed, sells_placed, elapsed_ms,
    )

    await _broadcast("bot_tick", {
        "tick": _tick_count,
        "mode": TRADING_MODE,
        "real_enabled": _real_trading_enabled(),
        "prices": prices.get("prices", {}),
        "open_trades": open_trades,
        "portfolio": {
            "cash_aud": cash,
            "holdings_value_aud": open_vals,
            "total_value_aud": total_value,
        },
        "decisions": decisions,
        "buys_placed": buys_placed,
        "sells_placed": sells_placed,
        "elapsed_ms": round(elapsed_ms),
    })
