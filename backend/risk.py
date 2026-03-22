"""Risk management — hard-coded stop loss 4%, take profit 8%."""
from config import STOP_LOSS_PCT, TAKE_PROFIT_PCT


def check_exit_signals(entry_price: float, current_price: float) -> dict:
    """
    Returns a dict with:
      - action: 'sell' | 'hold'
      - reason: human-readable explanation
      - pnl_pct: current PnL as a percentage
    """
    pnl_pct = (current_price - entry_price) / entry_price

    if pnl_pct <= -STOP_LOSS_PCT:
        return {
            "action": "sell",
            "reason": f"Stop loss triggered at {pnl_pct:.2%} (limit: -{STOP_LOSS_PCT:.0%})",
            "pnl_pct": pnl_pct,
        }

    if pnl_pct >= TAKE_PROFIT_PCT:
        return {
            "action": "sell",
            "reason": f"Take profit triggered at {pnl_pct:.2%} (target: +{TAKE_PROFIT_PCT:.0%})",
            "pnl_pct": pnl_pct,
        }

    return {
        "action": "hold",
        "reason": f"Within risk bounds at {pnl_pct:.2%}",
        "pnl_pct": pnl_pct,
    }


def max_position_size(balance_aud: float, price: float, risk_fraction: float = 0.10) -> dict:
    """
    Caps a single trade to risk_fraction of available balance.
    Returns the recommended AUD spend and coin quantity.
    """
    aud_to_spend = balance_aud * risk_fraction
    quantity = aud_to_spend / price
    return {"aud_to_spend": round(aud_to_spend, 2), "quantity": round(quantity, 8)}


def validate_trade(
    side: str,
    coin: str,
    aud_value: float,
    balance_aud: float,
    open_positions: list,
) -> dict:
    """Basic pre-trade validation. Returns {'ok': bool, 'reason': str}."""
    max_open = 5
    if side == "buy":
        if aud_value > balance_aud:
            return {"ok": False, "reason": "Insufficient AUD balance"}
        if len(open_positions) >= max_open:
            return {"ok": False, "reason": f"Max {max_open} open positions reached"}
        if aud_value < 10:
            return {"ok": False, "reason": "Minimum trade size is AUD 10"}
    return {"ok": True, "reason": "Validation passed"}
