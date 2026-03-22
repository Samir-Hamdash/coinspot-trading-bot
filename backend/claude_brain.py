"""Claude AI decision engine — analyses market data and returns a list of trading decisions."""
import json
import logging
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, TRADING_MODE
from risk import MAX_TRADE_SIZE_PERCENT, STOP_LOSS_PERCENT, TAKE_PROFIT_PERCENT

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

_SYSTEM_PROMPT = f"""You are a crypto trading AI operating on CoinSpot (Australian exchange).

You have full memory of all past trades, price history, win rates, and best/worst performing coins.
Your goal is capital preservation first, profit second.

Hard risk limits (enforced by code — you cannot override these):
- Stop loss: {STOP_LOSS_PERCENT:.0f}% per trade
- Take profit: {TAKE_PROFIT_PERCENT:.0f}% per trade
- Max position size: {MAX_TRADE_SIZE_PERCENT:.0f}% of total portfolio per trade
- Max 5 open positions at once

Your responsibilities:
1. Analyse price trends across ALL coins in the provided data
2. Identify bullish opportunities (buy signals) using momentum, volume, and historical patterns
3. Identify bearish signals on OPEN positions (sell-to-close signals)
4. Learn from past trade outcomes — avoid repeating losing patterns
5. Be conservative: only recommend high-confidence trades

You MUST respond with a valid JSON array — one object per coin you have an opinion on.
Coins not mentioned are implicitly "hold".

Response schema (array):
[
  {{
    "coin": "BTC",
    "action": "buy" | "sell" | "hold",
    "confidence": 0-100,
    "reasoning": "concise explanation referencing specific data points",
    "trend": "bullish" | "bearish" | "neutral"
  }},
  ...
]

Rules:
- Only recommend "buy" if confidence >= 60
- Only recommend "sell" on coins that are in the open_positions list
- Include at most 3 "buy" recommendations per cycle
- Always explain reasoning with specific reference to price data or past performance
- Return an empty array [] if conditions do not warrant any action
- Do NOT wrap in markdown code fences — return raw JSON only
"""


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that Claude sometimes adds despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first line (```json or ```) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


def _validate_decisions(raw: list[Any]) -> list[dict]:
    """
    Validate and normalise the list Claude returns.
    Drops malformed entries rather than crashing.
    """
    valid = []
    seen_coins: set[str] = set()
    buy_count = 0

    for item in raw:
        if not isinstance(item, dict):
            continue

        coin = str(item.get("coin", "")).upper().strip()
        action = str(item.get("action", "hold")).lower().strip()
        confidence = item.get("confidence", 0)
        reasoning = str(item.get("reasoning", ""))
        trend = str(item.get("trend", "neutral")).lower().strip()

        if not coin:
            continue
        if action not in ("buy", "sell", "hold"):
            log.warning("Invalid action '%s' for %s — skipping", action, coin)
            continue
        if coin in seen_coins:
            log.warning("Duplicate coin %s in response — skipping", coin)
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(100.0, confidence))
        if trend not in ("bullish", "bearish", "neutral"):
            trend = "neutral"

        # Enforce confidence floor for buys
        if action == "buy" and confidence < 60:
            log.info("Skipping low-confidence buy for %s (%.0f%%)", coin, confidence)
            continue

        # Cap buy recommendations at 3 per cycle
        if action == "buy":
            buy_count += 1
            if buy_count > 3:
                log.info("Buy cap reached — dropping %s", coin)
                continue

        seen_coins.add(coin)
        valid.append({
            "coin": coin,
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
            "trend": trend,
        })

    return valid


async def analyse_market(
    market_data: dict,
    portfolio: dict,
    memory_summary: dict,
) -> list[dict]:
    """
    Ask Claude to analyse market conditions and return a list of trading decisions.

    Parameters
    ----------
    market_data:
        CoinSpot prices payload: {"prices": {"BTC": {...}, ...}}
    portfolio:
        {"cash_aud": float, "total_value_aud": float, "open_trades": [...]}
    memory_summary:
        Full output of database.load_memory_summary()

    Returns
    -------
    List of validated decision dicts.  Empty list on failure — never raises.
    """
    # Build a compact but informative user message
    # Trim price history to last 20 points per coin to stay within token budget
    trimmed_price_history: dict[str, list] = {}
    for coin, points in memory_summary.get("price_history", {}).items():
        trimmed_price_history[coin] = points[-20:]

    user_payload = {
        "trading_mode": TRADING_MODE,
        "current_prices": market_data.get("prices", {}),
        "portfolio": {
            "cash_aud": portfolio.get("cash_aud"),
            "total_value_aud": portfolio.get("total_value_aud"),
            "open_positions": portfolio.get("open_trades", []),
        },
        "recent_price_history": trimmed_price_history,
        "performance": memory_summary.get("performance", {}),
        "recent_closed_trades": memory_summary.get("recent_trades", [])[-30:],
        "recent_decisions": memory_summary.get("recent_decisions", [])[-10:],
        "bot_memory": memory_summary.get("memory", {}),
    }

    user_message = (
        "Analyse the market data below and return your trading decisions as a JSON array.\n\n"
        + json.dumps(user_payload, indent=2, default=str)
    )

    try:
        response = await _client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIConnectionError as exc:
        log.error("Claude API connection error: %s", exc)
        return []
    except anthropic.RateLimitError as exc:
        log.error("Claude rate limit hit: %s", exc)
        return []
    except anthropic.APIStatusError as exc:
        log.error("Claude API error %s: %s", exc.status_code, exc.message)
        return []
    except Exception as exc:
        log.error("Unexpected Claude error: %s", exc)
        return []

    raw_text = _strip_fences(response.content[0].text)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        log.error("Claude JSON parse error: %s\nRaw response: %.300s", exc, raw_text)
        return []

    if not isinstance(parsed, list):
        # Claude occasionally wraps the array in an object
        if isinstance(parsed, dict):
            for key in ("decisions", "trades", "recommendations"):
                if isinstance(parsed.get(key), list):
                    parsed = parsed[key]
                    break
            else:
                log.error("Claude returned a dict instead of a list: %.200s", raw_text)
                return []
        else:
            log.error("Claude returned unexpected type %s", type(parsed))
            return []

    decisions = _validate_decisions(parsed)
    log.info(
        "Claude decisions: %d total (%d buy, %d sell, %d hold)",
        len(decisions),
        sum(1 for d in decisions if d["action"] == "buy"),
        sum(1 for d in decisions if d["action"] == "sell"),
        sum(1 for d in decisions if d["action"] == "hold"),
    )

    # Persist every decision to the database
    try:
        from database import log_trade_decision  # deferred to avoid circular import
        for d in decisions:
            await log_trade_decision(
                action=d["action"],
                coin=d["coin"],
                direction="long" if d["trend"] == "bullish" else (
                    "short" if d["trend"] == "bearish" else None
                ),
                confidence=d["confidence"] / 100.0,
                reasoning=d["reasoning"],
            )
    except Exception as exc:
        log.warning("Failed to persist decisions to DB: %s", exc)

    return decisions


# ── Legacy shim ───────────────────────────────────────────────────────────────

async def get_trading_decision(
    prices: dict,
    open_positions: list[dict],
    trade_history: list[dict],
    memory: dict,
    balance_aud: float,
) -> dict:
    """
    Legacy single-decision shim used by older bot.py call sites.
    Wraps analyse_market() and returns the highest-confidence non-hold decision,
    or a hold if there are none.
    """
    open_vals = sum(float(p.get("aud_value", 0)) for p in open_positions)
    portfolio = {
        "cash_aud": balance_aud,
        "total_value_aud": balance_aud + open_vals,
        "open_trades": open_positions,
    }
    decisions = await analyse_market(prices, portfolio, memory)
    actionable = [d for d in decisions if d["action"] != "hold"]
    if not actionable:
        return {
            "decision": "hold", "coin": None, "confidence": 0.0,
            "reasoning": "No high-confidence opportunities identified.",
            "trend": "neutral", "memory_update": {},
        }
    best = max(actionable, key=lambda d: d["confidence"])
    return {
        "decision": best["action"],
        "coin": best["coin"],
        "confidence": best["confidence"] / 100.0,
        "reasoning": best["reasoning"],
        "trend": best["trend"],
        "memory_update": {},
    }
