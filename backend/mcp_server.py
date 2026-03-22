"""
MCP server for CoinSpot Trading Bot.

Claude desktop connects to this server (via stdio) and calls tools to:
  - Get the latest market data the bot has collected
  - Submit trading decisions back to the bot
  - Inspect open trades, portfolio, and performance stats
  - Execute manual paper trades

IPC with bot.py / main.py uses the shared SQLite database:
  memory.pending_analysis  — JSON market snapshot written each tick by bot.py
  memory.analysis_status   — "idle" | "pending" | "processing" | "complete"
  memory.latest_decisions  — JSON array of decisions Claude submitted
  memory.paper_cash_aud    — live paper balance (read/written by both sides)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# When run as "python backend/mcp_server.py" from the project root,
# make sure "backend/" is on sys.path so relative imports work.
sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP

from config import PAPER_BALANCE, TRADING_MODE
from database import (
    close_trade,
    get_memory,
    get_open_trades,
    init_db,
    load_memory_summary,
    log_trade_decision,
    open_trade,
    set_memory,
)
from risk import (
    MAX_TRADE_SIZE_PERCENT,
    STOP_LOSS_PERCENT,
    TAKE_PROFIT_PERCENT,
)

log = logging.getLogger(__name__)

# ── FastMCP server ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    "CoinSpot Trading Bot",
    instructions=f"""You are the AI brain of a CoinSpot cryptocurrency trading bot running in {TRADING_MODE} mode.

HOW TO RUN AN ANALYSIS CYCLE:
1. Call analyse_market() — returns current prices, portfolio, and trading history
2. Study the data: look for trends, momentum, and patterns in price history
3. Call submit_trade_decisions() with your decisions as a JSON array

DECISION FORMAT (JSON array):
[
  {{
    "coin": "BTC",
    "action": "buy" | "sell" | "hold",
    "confidence": 0-100,
    "reasoning": "specific data-driven explanation",
    "trend": "bullish" | "bearish" | "neutral"
  }}
]

HARD-CODED RISK RULES (enforced by the bot, cannot be changed):
- Stop loss:       {STOP_LOSS_PERCENT:.0f}% below entry — auto-closed every tick
- Take profit:     {TAKE_PROFIT_PERCENT:.0f}% above entry — auto-closed every tick
- Max trade size:  {MAX_TRADE_SIZE_PERCENT:.0f}% of total portfolio per trade
- Max open positions: 5
- Min confidence for buys: 60%
- Max 3 buys per cycle

STRATEGY GUIDELINES:
- Prioritise capital preservation over profit
- Only recommend "buy" with confidence >= 60
- Only recommend "sell" on coins with open positions
- Return [] if there are no clear opportunities
""",
)


# ── Tools ──────────────────────────────────────────────────────────────────────


@mcp.tool()
async def analyse_market() -> str:
    """
    Get the latest market snapshot the bot has collected: live prices, current
    portfolio, price history, and past trade performance.

    After you analyse this data, call submit_trade_decisions() with your decisions.
    Returns a JSON object with keys: prices, portfolio, price_history, performance,
    recent_trades, open_positions, and an instruction reminder.
    """
    await init_db()

    pending_json = await get_memory("pending_analysis")
    if pending_json:
        data = json.loads(pending_json)
        await set_memory("analysis_status", "processing")
        # Add instruction reminder so Claude knows the next step
        data["_instruction"] = (
            "Analyse the above data. "
            "Call submit_trade_decisions() with your decisions as a JSON array. "
            "Return [] if no clear opportunities exist."
        )
        return json.dumps(data, indent=2, default=str)

    # Fallback: build a fresh snapshot from DB (no pending tick data)
    from bot import get_last_prices  # deferred — bot may not be running
    prices = get_last_prices()

    balance_str = await get_memory("paper_cash_aud")
    paper_balance = float(balance_str) if balance_str else PAPER_BALANCE
    open_trades = await get_open_trades()
    holdings = sum(float(t.get("value_aud", 0)) for t in open_trades)
    memory_summary = await load_memory_summary()

    snapshot = _build_compact_snapshot(prices, paper_balance, holdings, open_trades, memory_summary)
    snapshot["_instruction"] = (
        "No pending bot tick. This is the latest known data. "
        "Call submit_trade_decisions() with your decisions."
    )
    return json.dumps(snapshot, indent=2, default=str)


@mcp.tool()
async def submit_trade_decisions(decisions_json: str) -> str:
    """
    Submit your trading decisions as a JSON array. The bot will validate and
    execute them on the next opportunity.

    Expected format:
      [{"coin": "BTC", "action": "buy|sell|hold", "confidence": 75,
        "reasoning": "...", "trend": "bullish|bearish|neutral"}]

    Returns confirmation with the number of decisions accepted.
    """
    await init_db()

    try:
        raw = json.loads(decisions_json)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON: {exc}"})

    if not isinstance(raw, list):
        # Unwrap common wrapper objects
        for key in ("decisions", "trades", "recommendations"):
            if isinstance(raw, dict) and isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            return json.dumps({"error": "decisions_json must be a JSON array"})

    valid: list[dict] = []
    buy_count = 0
    seen: set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        coin = str(item.get("coin", "")).upper().strip()
        action = str(item.get("action", "hold")).lower().strip()
        if not coin or action not in ("buy", "sell", "hold"):
            continue
        if coin in seen:
            continue
        seen.add(coin)

        try:
            confidence = float(item.get("confidence", 70))
        except (TypeError, ValueError):
            confidence = 70.0
        confidence = max(0.0, min(100.0, confidence))

        trend = str(item.get("trend", "neutral")).lower()
        if trend not in ("bullish", "bearish", "neutral"):
            trend = "neutral"

        # Enforce confidence floor for buys
        if action == "buy" and confidence < 60:
            continue
        # Cap buys at 3 per cycle
        if action == "buy":
            buy_count += 1
            if buy_count > 3:
                continue

        valid.append({
            "coin": coin,
            "action": action,
            "confidence": confidence,
            "reasoning": str(item.get("reasoning", "")),
            "trend": trend,
        })

    await set_memory("latest_decisions", json.dumps(valid))
    await set_memory("analysis_status", "complete")

    # Persist to trade_decisions table
    for d in valid:
        try:
            await log_trade_decision(
                action=d["action"],
                coin=d["coin"],
                direction="long" if d["trend"] == "bullish" else (
                    "short" if d["trend"] == "bearish" else None
                ),
                confidence=d["confidence"] / 100.0,
                reasoning=d["reasoning"],
            )
        except Exception:
            pass

    actionable = [d for d in valid if d["action"] != "hold"]
    return json.dumps({
        "status": "ok",
        "decisions_accepted": len(valid),
        "trades_to_execute": len(actionable),
        "summary": [f"{d['action'].upper()} {d['coin']} ({d['confidence']:.0f}%)" for d in actionable],
        "message": "Bot will execute these on the next tick (within 60s)." if actionable else "No trades to execute.",
    })


@mcp.tool()
async def get_open_trades_tool() -> str:
    """
    Get all currently open trading positions with entry prices and P&L estimates.
    """
    await init_db()
    trades = await get_open_trades()

    # Enrich with stop-loss and take-profit prices
    from bot import get_last_prices
    prices = get_last_prices()
    price_map = prices.get("prices", {}) if prices else {}

    enriched = []
    for t in trades:
        coin = t["coin"]
        entry = float(t["entry_price"])
        qty = float(t["quantity"])

        pd = price_map.get(coin) or price_map.get(coin.lower(), {})
        current = float(pd.get("last") or pd.get("bid") or entry)
        pnl_aud = (current - entry) * qty
        pnl_pct = ((current - entry) / entry * 100) if entry else 0.0

        enriched.append({
            **{k: t[k] for k in ("id", "coin", "direction", "entry_price", "quantity", "value_aud", "entry_time", "mode")},
            "current_price": current,
            "pnl_aud": round(pnl_aud, 4),
            "pnl_percent": round(pnl_pct, 4),
            "stop_loss_price": round(entry * (1 - STOP_LOSS_PERCENT / 100), 4),
            "take_profit_price": round(entry * (1 + TAKE_PROFIT_PERCENT / 100), 4),
        })

    return json.dumps(enriched, indent=2, default=str)


@mcp.tool()
async def get_memory_stats() -> str:
    """
    Get bot performance statistics: win rate, trade history length, and the
    best/worst performing coins based on closed trades.
    """
    await init_db()
    summary = await load_memory_summary()
    result = {
        "total_closed_trades": summary.get("total_trades", 0),
        "wins": summary.get("wins", 0),
        "losses": summary.get("losses", 0),
        "win_rate_pct": summary.get("win_rate_pct", 0.0),
        "best_coins": summary.get("best_coins", [])[:5],
        "worst_coins": summary.get("worst_coins", [])[:5],
        "data_history_days": summary.get("data_history_days"),
        "tracked_coins": len(summary.get("price_history", {})),
    }
    return json.dumps(result, indent=2)


@mcp.tool()
async def execute_paper_trade(
    coin: str,
    action: str,
    amount_aud: float = 0.0,
    reasoning: str = "",
) -> str:
    """
    Manually execute a paper trade immediately (bypasses the 60s bot cycle).
    action: 'buy' or 'sell'
    amount_aud: AUD to spend on a buy. For sell, pass 0 to close the full position.
    """
    await init_db()
    coin = coin.upper().strip()
    action = action.lower().strip()

    if action not in ("buy", "sell"):
        return json.dumps({"error": "action must be 'buy' or 'sell'"})

    balance_str = await get_memory("paper_cash_aud")
    paper_balance = float(balance_str) if balance_str else PAPER_BALANCE

    current_price = await _get_current_price(coin)

    if action == "buy":
        if amount_aud <= 0:
            return json.dumps({"error": "amount_aud must be positive for a buy"})
        if not current_price:
            return json.dumps({"error": f"No live price for {coin}. Run analyse_market() first to load prices."})
        if amount_aud > paper_balance:
            return json.dumps({"error": f"Insufficient balance: AUD {paper_balance:.2f} available, AUD {amount_aud:.2f} requested"})

        qty = round(amount_aud / current_price, 8)
        trade_id = await open_trade(
            coin=coin, direction="long",
            entry_price=current_price, quantity=qty,
            value_aud=amount_aud, mode="paper",
        )
        new_balance = paper_balance - amount_aud
        await set_memory("paper_cash_aud", new_balance)

        return json.dumps({
            "status": "ok", "action": "buy", "coin": coin,
            "qty": qty, "price": current_price, "aud_spent": amount_aud,
            "new_balance_aud": round(new_balance, 2), "trade_id": trade_id,
            "stop_loss_price": round(current_price * (1 - STOP_LOSS_PERCENT / 100), 4),
            "take_profit_price": round(current_price * (1 + TAKE_PROFIT_PERCENT / 100), 4),
        })

    else:  # sell
        trades = await get_open_trades()
        position = next((t for t in trades if t["coin"] == coin), None)
        if not position:
            return json.dumps({"error": f"No open position found for {coin}"})

        price = current_price or float(position["entry_price"])
        qty = float(position["quantity"])
        aud_val = qty * price

        closed = await close_trade(position["id"], price, "mcp_manual")
        new_balance = paper_balance + aud_val
        await set_memory("paper_cash_aud", new_balance)

        return json.dumps({
            "status": "ok", "action": "sell", "coin": coin,
            "qty": qty, "price": price, "aud_received": round(aud_val, 2),
            "pnl_aud": round(closed["pnl_aud"], 4) if closed else None,
            "pnl_percent": round(closed["pnl_percent"], 4) if closed else None,
            "new_balance_aud": round(new_balance, 2),
        })


@mcp.tool()
async def get_portfolio() -> str:
    """
    Get the current portfolio state: cash balance, open positions, and total value.
    """
    await init_db()

    balance_str = await get_memory("paper_cash_aud")
    paper_balance = float(balance_str) if balance_str else PAPER_BALANCE
    trades = await get_open_trades()
    holdings = sum(float(t.get("value_aud", 0)) for t in trades)

    return json.dumps({
        "mode": TRADING_MODE,
        "cash_aud": round(paper_balance, 2),
        "holdings_value_aud": round(holdings, 2),
        "total_value_aud": round(paper_balance + holdings, 2),
        "open_positions": len(trades),
        "positions": [
            {
                "coin": t["coin"],
                "direction": t["direction"],
                "entry_price": t["entry_price"],
                "quantity": t["quantity"],
                "value_aud": t["value_aud"],
                "entry_time": t["entry_time"],
            }
            for t in trades
        ],
    }, indent=2, default=str)


# ── Internal helpers ───────────────────────────────────────────────────────────


async def _get_current_price(coin: str) -> float | None:
    """Read latest price for a coin from the pending analysis snapshot."""
    pending_json = await get_memory("pending_analysis")
    if not pending_json:
        return None
    data = json.loads(pending_json)
    price_map = data.get("prices", {}).get("prices", {})
    pd = price_map.get(coin) or price_map.get(coin.lower(), {})
    last = pd.get("last") or pd.get("ask") or pd.get("bid")
    return float(last) if last else None


def _build_compact_snapshot(
    prices: dict,
    cash: float,
    holdings: float,
    open_trades: list[dict],
    memory_summary: dict,
) -> dict:
    """Build a context-window-friendly market snapshot (no raw 500-point histories)."""
    # Trim price history to last 5 points per coin
    trimmed: dict[str, list] = {}
    for coin, points in memory_summary.get("price_history", {}).items():
        trimmed[coin] = points[-5:]

    return {
        "prices": prices,
        "portfolio": {
            "cash_aud": round(cash, 2),
            "holdings_value_aud": round(holdings, 2),
            "total_value_aud": round(cash + holdings, 2),
            "open_positions": open_trades,
        },
        "price_history_last5": trimmed,
        "performance": memory_summary.get("performance", {}),
        "recent_trades": memory_summary.get("recent_trades", [])[-20:],
        "bot_memory_notes": memory_summary.get("memory", {}),
    }


# ── Public helper imported by bot.py ──────────────────────────────────────────


async def request_mcp_analysis(
    prices: dict,
    portfolio: dict,
    memory_summary: dict,
    timeout_seconds: float = 55.0,
) -> list[dict]:
    """
    Called by bot.py instead of claude_brain.analyse_market().

    Writes the current market snapshot to the shared SQLite memory table, then
    polls for Claude desktop to call analyse_market() and submit_trade_decisions().

    If Claude desktop is not connected or doesn't respond within `timeout_seconds`,
    returns an empty list (no trades this tick).
    """
    snapshot = _build_compact_snapshot(
        prices,
        portfolio.get("cash_aud", 0),
        portfolio.get("holdings_value_aud", 0),
        portfolio.get("open_trades", []),
        memory_summary,
    )
    snapshot["requested_at"] = datetime.now(timezone.utc).isoformat()

    await set_memory("pending_analysis", json.dumps(snapshot, default=str))
    await set_memory("analysis_status", "pending")

    log.info("MCP: market snapshot ready — waiting up to %.0fs for Claude desktop…", timeout_seconds)

    poll_interval = 0.5
    max_polls = int(timeout_seconds / poll_interval)

    for i in range(max_polls):
        await asyncio.sleep(poll_interval)
        status = await get_memory("analysis_status")
        if status == "complete":
            raw = await get_memory("latest_decisions")
            await set_memory("analysis_status", "idle")
            if raw:
                try:
                    decisions = json.loads(raw)
                    log.info(
                        "MCP: received %d decisions from Claude desktop "
                        "(%d buy, %d sell, %d hold)",
                        len(decisions),
                        sum(1 for d in decisions if d["action"] == "buy"),
                        sum(1 for d in decisions if d["action"] == "sell"),
                        sum(1 for d in decisions if d["action"] == "hold"),
                    )
                    return decisions
                except json.JSONDecodeError:
                    return []
            return []

        # Log a reminder every 15 seconds
        if i > 0 and (i * poll_interval) % 15 == 0:
            log.info(
                "MCP: still waiting for Claude desktop… (%.0fs elapsed). "
                "Open Claude desktop and call analyse_market() to proceed.",
                i * poll_interval,
            )

    log.warning(
        "MCP: timed out after %.0fs — Claude desktop did not respond. "
        "Skipping AI analysis this tick. "
        "To fix: open Claude desktop, ensure the coinspot-trading-bot MCP server is connected, "
        "then say: 'Call analyse_market() and submit_trade_decisions() with your analysis.'",
        timeout_seconds,
    )
    await set_memory("analysis_status", "idle")
    return []


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO)
    port = os.getenv("MCP_PORT")

    if port:
        # HTTP SSE transport — useful for testing outside Claude desktop
        log.info("Starting MCP server on SSE transport (port %s)", port)
        mcp.run(transport="sse", port=int(port))
    else:
        # stdio transport — Claude desktop default
        mcp.run()
