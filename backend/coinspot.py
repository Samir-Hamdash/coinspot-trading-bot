"""CoinSpot API v2 client — HMAC-SHA512, retries, structured logging."""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from config import COINSPOT_API_KEY, COINSPOT_API_SECRET, COINSPOT_BASE_URL

log = logging.getLogger(__name__)

# ── Retry policy ──────────────────────────────────────────────────────────────
_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]   # seconds between attempts
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# ── HMAC helpers ──────────────────────────────────────────────────────────────

def _sign(payload_str: str) -> str:
    """Return HMAC-SHA512 hex digest of payload_str using the API secret."""
    return hmac.new(
        COINSPOT_API_SECRET.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()


def _build_signed_request(payload: dict) -> tuple[str, dict]:
    """
    Stamp payload with a millisecond nonce, serialise it, and return
    (body_str, headers).  The same serialised body is used for both the
    HMAC and the HTTP body so the signature cannot drift.
    """
    payload = {**payload, "nonce": int(time.time() * 1000)}
    body = json.dumps(payload, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "key": COINSPOT_API_KEY,
        "sign": _sign(body),
    }
    return body, headers


# ── Low-level transport ───────────────────────────────────────────────────────

async def _request_with_retry(
    method: str,
    url: str,
    *,
    content: str | None = None,
    headers: dict | None = None,
    params: dict | None = None,
    label: str = "",
) -> httpx.Response | None:
    """
    Execute an HTTP request with exponential-backoff retries.
    Returns the Response on success, None if all retries are exhausted.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(_MAX_RETRIES):
            try:
                if method == "POST":
                    resp = await client.post(url, content=content, headers=headers)
                else:
                    resp = await client.get(url, params=params, headers=headers)

                if resp.status_code in _RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"Retryable {resp.status_code}", request=resp.request, response=resp
                    )

                resp.raise_for_status()
                log.debug("%s %s -> %d", method, label or url, resp.status_code)
                return resp

            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                log.warning(
                    "%s %s attempt %d/%d failed: %s — retrying in %.1fs",
                    method, label or url, attempt + 1, _MAX_RETRIES, exc, wait,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(wait)

    log.error("%s %s — all %d retries exhausted", method, label or url, _MAX_RETRIES)
    return None


async def _post(path: str, payload: dict | None = None) -> dict | None:
    body, headers = _build_signed_request(payload or {})
    url = f"{COINSPOT_BASE_URL}{path}"
    resp = await _request_with_retry("POST", url, content=body, headers=headers, label=path)
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception as exc:
        log.error("JSON decode error for %s: %s", path, exc)
        return None


async def _get(path: str, params: dict | None = None) -> Any | None:
    url = f"{COINSPOT_BASE_URL}{path}"
    resp = await _request_with_retry("GET", url, params=params, label=path)
    if resp is None:
        return None
    try:
        return resp.json()
    except Exception as exc:
        log.error("JSON decode error for %s: %s", path, exc)
        return None


# ── DB audit helper ───────────────────────────────────────────────────────────

async def _audit(action: str, coin: str | None, detail: str) -> None:
    """
    Write an API call record to trade_decisions so every request is traceable.
    Import is deferred to avoid a circular import at module load time.
    """
    try:
        from database import log_trade_decision  # noqa: PLC0415
        await log_trade_decision(
            action=action,
            coin=coin,
            direction=None,
            confidence=None,
            reasoning=detail,
        )
    except Exception as exc:
        log.warning("Audit log failed (%s): %s", action, exc)


# ── Public endpoints ──────────────────────────────────────────────────────────

async def get_all_latest_prices() -> dict | None:
    """
    Return latest AUD buy/sell/last prices for all traded coins.

    Response shape (from CoinSpot pubapi):
        {"status": "ok", "prices": {"BTC": {"bid": ..., "ask": ..., "last": ...}, ...}}

    Returns None on failure.
    """
    result = await _get("/pubapi/v2/latest")
    if result is None:
        await _audit("api_error", None, "get_all_latest_prices failed after retries")
        return None
    await _audit("prices_fetched", None, f"{len(result.get('prices', {}))} coins retrieved")
    return result


async def get_coin_price(coin: str) -> dict | None:
    """
    Return latest AUD prices for a single coin.
    Returns None on failure.
    """
    result = await _get(f"/pubapi/v2/latest/{coin.upper()}")
    if result is None:
        await _audit("api_error", coin, f"get_coin_price({coin}) failed")
        return None
    return result


# ── Private endpoints ─────────────────────────────────────────────────────────

async def get_my_balances() -> dict | None:
    """
    Return AUD cash balance plus all coin holdings.

    Normalised return shape:
        {
          "aud": float,                  # available AUD
          "holdings": {
              "BTC": {"balance": float, "audbalance": float, "rate": float},
              ...
          },
          "raw": { ... }                 # original CoinSpot response
        }

    Returns None on failure.
    """
    raw = await _post("/api/v2/my/balances")
    if raw is None:
        await _audit("api_error", None, "get_my_balances failed after retries")
        return None

    balances = raw.get("balances", {})
    aud_entry = balances.get("AUD", {})
    aud_cash = float(aud_entry.get("balance", 0))

    holdings = {
        coin: {
            "balance": float(data.get("balance", 0)),
            "audbalance": float(data.get("audbalance", 0)),
            "rate": float(data.get("rate", 0)),
        }
        for coin, data in balances.items()
        if coin != "AUD" and float(data.get("balance", 0)) > 0
    }

    total_holdings_aud = sum(h["audbalance"] for h in holdings.values())
    await _audit(
        "balances_fetched",
        None,
        f"AUD={aud_cash:.2f}, holdings_aud={total_holdings_aud:.2f}, coins={list(holdings)[:10]}",
    )
    return {"aud": aud_cash, "holdings": holdings, "raw": raw}


async def place_buy_order(coin: str, amount_aud: float) -> dict | None:
    """
    Place a market buy order spending amount_aud AUD on coin.

    Uses the CoinSpot market buy endpoint (/api/v2/my/buy/now) which
    fills immediately at the current ask without requiring a rate.

    Returns the raw CoinSpot response dict, or None on failure.
    """
    coin = coin.upper()
    payload = {
        "cointype": coin,
        "amounttype": "aud",
        "amount": round(amount_aud, 2),
    }
    log.info("BUY %s for AUD %.2f (market)", coin, amount_aud)
    result = await _post("/api/v2/my/buy/now", payload)

    if result is None:
        await _audit(
            "buy_failed", coin,
            f"place_buy_order({coin}, {amount_aud:.2f}) failed after retries",
        )
        return None

    status = result.get("status", "unknown")
    await _audit(
        "buy_placed", coin,
        f"market buy AUD {amount_aud:.2f} -> status={status} order={result.get('buyid', result.get('id', 'n/a'))}",
    )
    log.info("BUY %s AUD %.2f -> status=%s", coin, amount_aud, status)
    return result


async def place_sell_order(coin: str, quantity: float) -> dict | None:
    """
    Place a market sell order for quantity units of coin.

    Uses /api/v2/my/sell/now (market sell — fills at current bid).
    Intended for sell-to-close on AI bearish signals or risk exits.

    Returns the raw CoinSpot response dict, or None on failure.
    """
    coin = coin.upper()
    payload = {
        "cointype": coin,
        "amount": round(quantity, 8),
        "amounttype": "coin",
    }
    log.info("SELL %s qty=%.8f (market)", coin, quantity)
    result = await _post("/api/v2/my/sell/now", payload)

    if result is None:
        await _audit(
            "sell_failed", coin,
            f"place_sell_order({coin}, qty={quantity:.8f}) failed after retries",
        )
        return None

    status = result.get("status", "unknown")
    await _audit(
        "sell_placed", coin,
        f"market sell qty={quantity:.8f} -> status={status} order={result.get('sellid', result.get('id', 'n/a'))}",
    )
    log.info("SELL %s qty=%.8f -> status=%s", coin, quantity, status)
    return result


async def get_open_orders() -> dict | None:
    """
    Return all currently open buy and sell orders.

    Response shape:
        {"buyorders": [...], "sellorders": [...]}

    Returns None on failure.
    """
    result = await _post("/api/v2/orders/open")
    if result is None:
        await _audit("api_error", None, "get_open_orders failed after retries")
        return None

    buy_count = len(result.get("buyorders", []))
    sell_count = len(result.get("sellorders", []))
    await _audit("open_orders_fetched", None, f"open: {buy_count} buys, {sell_count} sells")
    return result


async def get_order_history(coin: str | None = None, limit: int = 200) -> dict | None:
    """
    Return completed order history, optionally filtered to a single coin.

    CoinSpot returns up to 500 records per call.  We expose a limit param
    so callers can request a smaller window.

    Returns None on failure.
    """
    payload: dict = {}
    if coin:
        payload["cointype"] = coin.upper()

    result = await _post("/api/v2/orders/completed", payload)
    if result is None:
        await _audit(
            "api_error", coin,
            f"get_order_history(coin={coin}) failed after retries",
        )
        return None

    buy_orders = result.get("buyorders", [])[:limit]
    sell_orders = result.get("sellorders", [])[:limit]
    await _audit(
        "order_history_fetched", coin,
        f"history: {len(buy_orders)} buys, {len(sell_orders)} sells (limit={limit})",
    )
    return {"buyorders": buy_orders, "sellorders": sell_orders}


# ── Convenience alias (used by bot.py / legacy code) ─────────────────────────

async def get_latest_prices() -> dict | None:
    """Alias for get_all_latest_prices() — keeps bot.py unchanged."""
    return await get_all_latest_prices()


async def get_balances() -> dict | None:
    """Alias for get_my_balances() — keeps bot.py unchanged."""
    return await get_my_balances()
