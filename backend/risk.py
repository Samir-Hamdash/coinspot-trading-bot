"""Risk management — all limits are hard-coded and cannot be overridden."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # kept for future type stubs

log = logging.getLogger(__name__)

# HARD-CODED — DO NOT MODIFY
STOP_LOSS_PERCENT = 4.0
TAKE_PROFIT_PERCENT = 8.0
MAX_TRADE_SIZE_PERCENT = 20.0  # max 20% of total portfolio per trade

# Derived constants — also hard-coded, not read from config
_STOP_LOSS_FRACTION = STOP_LOSS_PERCENT / 100.0      # 0.04
_TAKE_PROFIT_FRACTION = TAKE_PROFIT_PERCENT / 100.0  # 0.08
_MAX_TRADE_FRACTION = MAX_TRADE_SIZE_PERCENT / 100.0 # 0.20

_MIN_TRADE_AUD = 10.0    # CoinSpot minimum order value
_MAX_OPEN_TRADES = 5     # hard cap on concurrent positions


# ── check_open_trades ─────────────────────────────────────────────────────────

def check_open_trades(
    open_trades: list[dict],
    current_prices: dict,
) -> list[dict]:
    """
    Evaluate every open trade against current market prices.

    Parameters
    ----------
    open_trades:
        Rows from the open_trades table.  Each dict must contain at minimum:
          id, coin, direction ('long'|'short'), entry_price, quantity, value_aud
    current_prices:
        CoinSpot prices payload:
          {"prices": {"BTC": {"bid": ..., "ask": ..., "last": ...}, ...}}

    Returns
    -------
    List of trades that have breached stop-loss or take-profit, each enriched
    with:
      - current_price   float
      - pnl_aud         float
      - pnl_percent     float
      - exit_reason     'stop_loss' | 'take_profit'
      - exit_action     always 'sell'
      - message         human-readable description
    """
    exits: list[dict] = []
    prices = current_prices.get("prices", {})

    for trade in open_trades:
        coin = trade.get("coin", "").upper()
        price_data = prices.get(coin) or prices.get(coin.lower(), {})

        # Use bid for long exits (what we'd actually receive selling into the book),
        # ask for short exits (what we'd pay to buy back).
        direction = trade.get("direction", "long")
        if direction == "long":
            current_price = float(price_data.get("bid") or price_data.get("last") or 0)
        else:
            current_price = float(price_data.get("ask") or price_data.get("last") or 0)

        if current_price <= 0:
            log.warning("No price data for %s — skipping risk check", coin)
            continue

        entry_price = float(trade["entry_price"])
        quantity = float(trade["quantity"])
        value_aud = float(trade["value_aud"])

        # PnL calculation respects trade direction
        if direction == "long":
            pnl_aud = (current_price - entry_price) * quantity
        else:  # short
            pnl_aud = (entry_price - current_price) * quantity

        pnl_percent = (pnl_aud / value_aud) * 100 if value_aud else 0.0

        # Round to 6 decimal places to avoid floating-point drift
        # (e.g. 0.92 - 1.00 = -0.07999999... in IEEE 754)
        pnl_percent = round(pnl_percent, 6)

        hit_stop = pnl_percent <= -STOP_LOSS_PERCENT
        hit_tp = pnl_percent >= TAKE_PROFIT_PERCENT

        if hit_stop or hit_tp:
            exit_reason = "stop_loss" if hit_stop else "take_profit"
            message = (
                f"{coin} {direction} hit {'stop loss' if hit_stop else 'take profit'}: "
                f"entry={entry_price:.4f} current={current_price:.4f} "
                f"pnl={pnl_percent:+.2f}% (AUD {pnl_aud:+.2f})"
            )
            log.info(message)
            exits.append({
                **trade,
                "current_price": current_price,
                "pnl_aud": round(pnl_aud, 2),
                "pnl_percent": round(pnl_percent, 4),
                "exit_reason": exit_reason,
                "exit_action": "sell",
                "message": message,
            })

    return exits


# ── calculate_trade_size ──────────────────────────────────────────────────────

def calculate_trade_size(portfolio_value_aud: float) -> dict:
    """
    Return the maximum AUD value allowed for a single new trade.

    Hard cap is MAX_TRADE_SIZE_PERCENT (20%) of total portfolio value,
    bounded below by the minimum order size.

    Parameters
    ----------
    portfolio_value_aud:
        Total portfolio value in AUD (cash + all open positions).

    Returns
    -------
    {
      "max_aud":         float,   # hard ceiling for this trade
      "portfolio_value": float,   # the input, for audit clarity
      "percent_used":    float,   # always MAX_TRADE_SIZE_PERCENT (20.0)
      "ok":              bool,    # False if portfolio is too small to trade
      "reason":          str,
    }
    """
    if portfolio_value_aud <= 0:
        return {
            "max_aud": 0.0,
            "portfolio_value": portfolio_value_aud,
            "percent_used": MAX_TRADE_SIZE_PERCENT,
            "ok": False,
            "reason": "Portfolio value is zero or negative",
        }

    max_aud = round(portfolio_value_aud * _MAX_TRADE_FRACTION, 2)

    if max_aud < _MIN_TRADE_AUD:
        return {
            "max_aud": max_aud,
            "portfolio_value": portfolio_value_aud,
            "percent_used": MAX_TRADE_SIZE_PERCENT,
            "ok": False,
            "reason": (
                f"Max trade size AUD {max_aud:.2f} is below the "
                f"minimum order size of AUD {_MIN_TRADE_AUD:.2f}"
            ),
        }

    return {
        "max_aud": max_aud,
        "portfolio_value": portfolio_value_aud,
        "percent_used": MAX_TRADE_SIZE_PERCENT,
        "ok": True,
        "reason": f"Max trade size: AUD {max_aud:.2f} ({MAX_TRADE_SIZE_PERCENT:.0f}% of AUD {portfolio_value_aud:.2f})",
    }


# ── validate_trade ────────────────────────────────────────────────────────────

def validate_trade(trade: dict, portfolio: dict) -> dict:
    """
    Gate check before any trade is submitted to the exchange.

    Parameters
    ----------
    trade:
        Proposed trade.  Expected keys:
          coin        str
          side        'buy' | 'sell'
          direction   'long' | 'short'
          aud_value   float   — AUD to spend (buy) or receive (sell)
          quantity    float   — coin units (required for sell)
    portfolio:
        Current portfolio state.  Expected keys:
          cash_aud          float   — available AUD balance
          total_value_aud   float   — cash + all open positions
          open_trades       list    — current open_trades rows

    Returns
    -------
    {"ok": bool, "reason": str, "checks": {check_name: bool}}
    The "checks" dict lets callers log exactly which gate failed.
    """
    checks: dict[str, bool] = {}
    failures: list[str] = []

    coin = trade.get("coin", "UNKNOWN").upper()
    side = trade.get("side", "buy")
    aud_value = float(trade.get("aud_value", 0))
    quantity = float(trade.get("quantity", 0))
    cash_aud = float(portfolio.get("cash_aud", 0))
    total_value_aud = float(portfolio.get("total_value_aud", 0))
    open_trades: list = portfolio.get("open_trades", [])

    # ── 1. Minimum order size ──────────────────────────────────────────────
    checks["min_order_size"] = aud_value >= _MIN_TRADE_AUD
    if not checks["min_order_size"]:
        failures.append(f"Trade AUD {aud_value:.2f} is below minimum {_MIN_TRADE_AUD:.2f}")

    if side == "buy":
        # ── 2. Max trade size (20% of portfolio) ──────────────────────────
        sizing = calculate_trade_size(total_value_aud)
        checks["max_trade_size"] = aud_value <= sizing["max_aud"]
        if not checks["max_trade_size"]:
            failures.append(
                f"Trade AUD {aud_value:.2f} exceeds max allowed "
                f"AUD {sizing['max_aud']:.2f} ({MAX_TRADE_SIZE_PERCENT:.0f}% of portfolio)"
            )

        # ── 3. Sufficient cash balance ─────────────────────────────────────
        checks["sufficient_balance"] = aud_value <= cash_aud
        if not checks["sufficient_balance"]:
            failures.append(
                f"Insufficient cash: need AUD {aud_value:.2f}, have AUD {cash_aud:.2f}"
            )

        # ── 4. Open positions cap ──────────────────────────────────────────
        checks["open_positions_cap"] = len(open_trades) < _MAX_OPEN_TRADES
        if not checks["open_positions_cap"]:
            failures.append(
                f"Already at max open positions ({_MAX_OPEN_TRADES})"
            )

        # ── 5. No duplicate position in same coin ──────────────────────────
        existing_coins = {t.get("coin", "").upper() for t in open_trades}
        checks["no_duplicate_coin"] = coin not in existing_coins
        if not checks["no_duplicate_coin"]:
            failures.append(f"Already holding an open position in {coin}")

    elif side == "sell":
        # ── 6. Must have a matching open position to close ─────────────────
        open_coins = {t.get("coin", "").upper() for t in open_trades}
        checks["position_exists"] = coin in open_coins
        if not checks["position_exists"]:
            failures.append(f"No open position found for {coin} to close")

        # ── 7. Quantity must be positive ───────────────────────────────────
        checks["valid_quantity"] = quantity > 0
        if not checks["valid_quantity"]:
            failures.append("Sell quantity must be greater than zero")

    ok = len(failures) == 0
    reason = "All checks passed" if ok else "; ".join(failures)

    if not ok:
        log.warning("Trade validation failed for %s %s: %s", side, coin, reason)

    return {"ok": ok, "reason": reason, "checks": checks}


# ── Legacy shims — kept so bot.py call sites don't need changing ──────────────

def check_exit_signals(entry_price: float, current_price: float) -> dict:
    """
    Single-trade exit signal check.  Wraps check_open_trades logic for
    callers that don't have a full open_trades list.

    Returns {"action": "sell"|"hold", "reason": str, "pnl_pct": float}
    """
    if entry_price <= 0:
        return {"action": "hold", "reason": "Invalid entry price", "pnl_pct": 0.0}

    pnl_pct = (current_price - entry_price) / entry_price * 100

    if pnl_pct <= -STOP_LOSS_PERCENT:
        return {
            "action": "sell",
            "reason": f"Stop loss triggered at {pnl_pct:+.2f}% (limit: -{STOP_LOSS_PERCENT:.1f}%)",
            "pnl_pct": pnl_pct,
        }
    if pnl_pct >= TAKE_PROFIT_PERCENT:
        return {
            "action": "sell",
            "reason": f"Take profit triggered at {pnl_pct:+.2f}% (target: +{TAKE_PROFIT_PERCENT:.1f}%)",
            "pnl_pct": pnl_pct,
        }
    return {
        "action": "hold",
        "reason": f"Within risk bounds at {pnl_pct:+.2f}%",
        "pnl_pct": pnl_pct,
    }


def max_position_size(balance_aud: float, price: float, risk_fraction: float = None) -> dict:
    """
    Legacy shim used by bot.py.  risk_fraction is ignored — the hard-coded
    MAX_TRADE_SIZE_PERCENT is always used regardless of what is passed in.
    """
    aud_to_spend = round(balance_aud * _MAX_TRADE_FRACTION, 2)
    quantity = round(aud_to_spend / price, 8) if price > 0 else 0.0
    return {"aud_to_spend": aud_to_spend, "quantity": quantity}
