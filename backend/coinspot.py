"""CoinSpot API client — wraps REST endpoints with HMAC-SHA512 signing."""
import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from config import COINSPOT_API_KEY, COINSPOT_API_SECRET, COINSPOT_BASE_URL


def _sign(secret: str, payload: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha512
    ).hexdigest()


def _build_headers(payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":"))
    sign = _sign(COINSPOT_API_SECRET, body)
    return {
        "Content-Type": "application/json",
        "key": COINSPOT_API_KEY,
        "sign": sign,
    }


async def _post(path: str, payload: dict | None = None) -> dict:
    if payload is None:
        payload = {}
    payload["nonce"] = int(time.time() * 1000)
    headers = _build_headers(payload)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{COINSPOT_BASE_URL}{path}",
            headers=headers,
            content=json.dumps(payload, separators=(",", ":")),
        )
        resp.raise_for_status()
        return resp.json()


async def _get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{COINSPOT_BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


# ── Public endpoints ──────────────────────────────────────────────────────────

async def get_latest_prices() -> dict:
    """Return latest buy/sell prices for all coins."""
    return await _get("/pubapi/v2/latest")


async def get_coin_price(coin: str) -> dict:
    """Return latest buy/sell for a specific coin (e.g. 'BTC')."""
    return await _get(f"/pubapi/v2/latest/{coin.upper()}")


# ── Private endpoints ─────────────────────────────────────────────────────────

async def get_balances() -> dict:
    return await _post("/api/v2/my/balances")


async def get_open_orders() -> dict:
    return await _post("/api/v2/orders/open")


async def get_completed_orders() -> dict:
    return await _post("/api/v2/orders/completed")


async def place_buy_order(coin: str, amount_aud: float, rate: float) -> dict:
    """Place a buy order. amount_aud is how many AUD to spend."""
    payload = {
        "cointype": coin.upper(),
        "amount": round(amount_aud / rate, 8),
        "rate": rate,
        "markettype": "AUD",
    }
    return await _post("/api/v2/my/buy", payload)


async def place_sell_order(coin: str, amount_coin: float, rate: float) -> dict:
    """Place a sell order. amount_coin is how many coins to sell."""
    payload = {
        "cointype": coin.upper(),
        "amount": amount_coin,
        "rate": rate,
        "markettype": "AUD",
    }
    return await _post("/api/v2/my/sell", payload)


async def cancel_buy_order(order_id: str) -> dict:
    return await _post("/api/v2/my/buy/cancel", {"id": order_id})


async def cancel_sell_order(order_id: str) -> dict:
    return await _post("/api/v2/my/sell/cancel", {"id": order_id})
