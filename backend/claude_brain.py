"""Claude AI decision engine — analyses market data and memory to make trading decisions."""
import json
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, STOP_LOSS_PCT, TAKE_PROFIT_PCT, TRADING_MODE

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = f"""You are an expert cryptocurrency trading assistant operating in {TRADING_MODE.upper()} mode.

Your job is to analyse market data, open positions, and recent trade history, then output a structured trading decision.

Rules you MUST follow:
1. Stop loss is hard-coded at {STOP_LOSS_PCT * 100:.0f}% — never recommend holding past this.
2. Take profit target is {TAKE_PROFIT_PCT * 100:.0f}% — consider taking profits here.
3. Maximum 5 open positions at any time.
4. Minimum trade size is AUD 10.
5. Never risk more than 10% of available balance on a single trade.
6. Provide clear, concise reasoning for every decision.

You MUST respond ONLY with valid JSON in this exact schema:
{{
  "decision": "buy" | "sell" | "hold",
  "coin": "BTC" | "ETH" | "XRP" | ... | null,
  "confidence": 0.0-1.0,
  "reasoning": "string explaining the decision",
  "risk_notes": "string with any risk considerations",
  "memory_update": {{
    "key": "value"  // optional key-value pairs to persist
  }}
}}
"""


async def get_trading_decision(
    prices: dict,
    open_positions: list[dict],
    trade_history: list[dict],
    memory: dict,
    balance_aud: float,
) -> dict[str, Any]:
    """Ask Claude for a trading decision given current market state."""

    user_content = json.dumps(
        {
            "current_prices": prices,
            "open_positions": open_positions,
            "recent_trades": trade_history[-20:] if trade_history else [],
            "memory": memory,
            "available_balance_aud": balance_aud,
            "trading_mode": TRADING_MODE,
        },
        indent=2,
    )

    message = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Here is the current market state. Provide your trading decision:\n\n{user_content}",
            }
        ],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {
            "decision": "hold",
            "coin": None,
            "confidence": 0.0,
            "reasoning": f"Failed to parse Claude response: {raw[:200]}",
            "risk_notes": "Parse error — defaulting to hold",
            "memory_update": {},
        }

    return decision


async def explain_position(position: dict, current_price: float) -> str:
    """Ask Claude to explain a specific open position in plain English."""
    message = _client.messages.create(
        model="claude-opus-4-6",
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Explain this open {position['coin']} position in 2-3 sentences for a retail trader:\n"
                    f"{json.dumps(position, indent=2)}\n"
                    f"Current price: {current_price}"
                ),
            }
        ],
    )
    return message.content[0].text.strip()
