"""
Kalshi WebSocket client: connect, subscribe to ticker, and delegate
per-market analytics updates to the market_analytics service.
"""
import asyncio
import json
import os
from typing import Dict, Any

import websockets

from app.services.market_analytics import compute_market_analytics
from app.services.kalshi_auth_service import build_websocket_auth_headers

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"


async def subscribe_to_ticker(websocket):
    """Subscribe to ticker channel (all markets)."""
    subscription = {
        "id": 1,
        "cmd": "subscribe",
        "params": {
            "channels": ["ticker"],
        },
    }
    await websocket.send(json.dumps(subscription))
    return subscription


async def process_message(
    message: str,
    redis_client,
) -> Dict[str, Any] | None:
    """
    Parse a WS message and update per-market analytics in Redis.
    Returns the parsed payload for logging; None if not ticker.
    """
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return None

    msg_type = data.get("type")
    if msg_type != "ticker":
        return data

    msg = data.get("msg")
    if not msg or not isinstance(msg, dict):
        return data

    ticker = msg.get("market_ticker")
    if not ticker:
        return data

    # Delegate computation to the analytics service
    analytics = compute_market_analytics(ticker, msg)

    # Store analytics in a dedicated Redis hash per market:
    # key: market:{ticker}, fields: price, bid, ask, spread, volume_1s, volume_10s, volume_60s, momentum, imbalance, last_trade_ts
    key = f"market:{ticker}"
    try:
        await redis_client.hset(
            key,
            mapping={k: str(v) for k, v in analytics.items()},
        )
        await redis_client.expire(key, 60)
    except Exception as e:
        print("Redis HSET error:", e)

    return {"type": "ticker", "msg": {**msg, **analytics}}


async def run_websocket_client():
    """Connect to Kalshi WS, subscribe to ticker, and maintain per-market analytics in Redis."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not set; required for Redis analytics")

    import redis.asyncio as redis
    redis_client = redis.from_url(redis_url, decode_responses=True)

    # Build auth headers for Kalshi WS (required for this endpoint)
    headers = build_websocket_auth_headers()
    extra_headers = list(headers.items()) if headers else []
    print("beginning connection to ws")
    try:
        async with websockets.connect(
            WS_URL,
            additional_headers=extra_headers,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as websocket:
            print("Connected to Kalshi WebSocket")
            await subscribe_to_ticker(websocket)
            print("Subscribed to ticker; updating per-market Redis keys")

            async for raw in websocket:
                try:
                    parsed = await process_message(raw, redis_client)
                    if parsed and parsed.get("type") == "ticker":
                        ticker = parsed.get("msg", {}).get("market_ticker")
                        price = parsed.get("msg", {}).get("price")
                        print("ticker:", ticker, price)
                except Exception as e:
                    print("Error processing message:", e)
    finally:
        print("reached finally")
        await redis_client.aclose()


def main():
    asyncio.run(run_websocket_client())


if __name__ == "__main__":
    main()
