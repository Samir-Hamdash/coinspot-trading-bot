"""Core bot loop — runs every 60 seconds via APScheduler."""
import asyncio
import logging
from datetime import datetime

from claude_brain import get_trading_decision
from coinspot import get_latest_prices, get_balances, place_buy_order, place_sell_order
from config import (
    BOT_INTERVAL_SECONDS,
    PAPER_BALANCE,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TRADING_MODE,
)
from database import (
    get_all_memory,
    get_open_positions,
    get_trades,
    log_bot_run,
    log_trade,
    set_memory,
)
from risk import check_exit_signals, max_position_size, validate_trade

log = logging.getLogger(__name__)

# In-memory state (also persisted to DB)
_paper_balance: float = PAPER_BALANCE
_paper_positions: list[dict] = []
_last_decision: dict = {}
_broadcast_callback = None  # Set by main.py to push WS updates


def set_broadcast_callback(cb):
    global _broadcast_callback
    _broadcast_callback = cb


def get_last_decision() -> dict:
    return _last_decision


async def _broadcast(event: str, data: dict):
    if _broadcast_callback:
        await _broadcast_callback({"event": event, "data": data})


async def _get_balance() -> float:
    global _paper_balance
    if TRADING_MODE == "paper":
        return _paper_balance
    try:
        result = await get_balances()
        aud = result.get("balances", {}).get("AUD", {}).get("balance", 0)
        return float(aud)
    except Exception as e:
        log.error("Failed to fetch live balance: %s", e)
        return 0.0


async def _check_stop_loss_take_profit(prices: dict):
    """Check all open positions against current prices and exit if needed."""
    positions = await get_open_positions()
    for pos in positions:
        coin = pos["coin"]
        price_data = prices.get("prices", {}).get(coin, {})
        current_price = float(price_data.get("last", pos["price"]))
        signal = check_exit_signals(pos["price"], current_price)

        if signal["action"] == "sell":
            log.info("Risk exit: %s — %s", coin, signal["reason"])
            qty = pos["quantity"]
            aud_val = qty * current_price
            pnl = aud_val - pos["aud_value"]

            if TRADING_MODE == "paper":
                global _paper_balance
                _paper_balance += aud_val
                # Mark position as closed (set pnl)
                await log_trade(
                    coin=coin, side="sell", mode="paper",
                    price=current_price, quantity=qty,
                    aud_value=aud_val, pnl=pnl,
                    reason=signal["reason"],
                )
            else:
                await place_sell_order(coin, qty, current_price)

            await _broadcast("position_closed", {"coin": coin, "pnl": pnl, "reason": signal["reason"]})


async def bot_tick():
    """Single bot cycle — fetch prices → check risk → ask Claude → execute."""
    global _last_decision, _paper_balance

    log.info("[%s] Bot tick — mode=%s", datetime.utcnow().isoformat(), TRADING_MODE)

    # 1. Fetch prices
    try:
        prices = await get_latest_prices()
    except Exception as e:
        log.error("Price fetch failed: %s", e)
        return

    # 2. Check stop loss / take profit on open positions
    await _check_stop_loss_take_profit(prices)

    # 3. Gather context for Claude
    balance = await _get_balance()
    open_positions = await get_open_positions()
    trade_history = await get_trades(50)
    memory = await get_all_memory()

    # 4. Ask Claude for a decision
    try:
        decision = await get_trading_decision(
            prices=prices,
            open_positions=open_positions,
            trade_history=trade_history,
            memory=memory,
            balance_aud=balance,
        )
    except Exception as e:
        log.error("Claude decision failed: %s", e)
        decision = {"decision": "hold", "coin": None, "reasoning": str(e), "confidence": 0}

    _last_decision = decision
    log.info("Decision: %s %s (confidence=%.2f)", decision.get("decision"), decision.get("coin"), decision.get("confidence", 0))

    # 5. Persist memory updates
    for k, v in decision.get("memory_update", {}).items():
        await set_memory(k, v)

    # 6. Execute trade
    action = decision.get("decision", "hold")
    coin = decision.get("coin")
    reason = decision.get("reasoning", "")

    if action == "buy" and coin:
        sizing = max_position_size(balance, 1)  # price=1 placeholder; we use AUD fraction
        price_data = prices.get("prices", {}).get(coin, {})
        price = float(price_data.get("ask", 0))
        if price > 0:
            sizing = max_position_size(balance, price)
            aud_spend = sizing["aud_to_spend"]
            validation = validate_trade("buy", coin, aud_spend, balance, open_positions)
            if validation["ok"]:
                if TRADING_MODE == "paper":
                    _paper_balance -= aud_spend
                    qty = sizing["quantity"]
                    await log_trade(coin, "buy", "paper", price, qty, aud_spend, reason=reason)
                    await _broadcast("trade_executed", {"side": "buy", "coin": coin, "aud": aud_spend})
                else:
                    await place_buy_order(coin, aud_spend, price)
            else:
                log.warning("Trade blocked: %s", validation["reason"])

    elif action == "sell" and coin:
        for pos in open_positions:
            if pos["coin"] == coin:
                price_data = prices.get("prices", {}).get(coin, {})
                price = float(price_data.get("bid", pos["price"]))
                aud_val = pos["quantity"] * price
                pnl = aud_val - pos["aud_value"]
                if TRADING_MODE == "paper":
                    _paper_balance += aud_val
                    await log_trade(coin, "sell", "paper", price, pos["quantity"], aud_val, pnl=pnl, reason=reason)
                    await _broadcast("trade_executed", {"side": "sell", "coin": coin, "pnl": pnl})
                else:
                    await place_sell_order(coin, pos["quantity"], price)

    # 7. Log run
    await log_bot_run(TRADING_MODE, action, reason, prices)
    await _broadcast("bot_tick", {"decision": decision, "balance": _paper_balance if TRADING_MODE == "paper" else balance})
