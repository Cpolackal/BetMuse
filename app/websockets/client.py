import json
from typing import Dict, Any

import websockets
from app.core.contract_buffer import Tick
from app.core.market_filter import is_allowed_market
from app.services.market_analytics import compute_market_analytics
from app.services.kalshi_auth_service import build_websocket_auth_headers

WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"


async def subscribe_to_ticker(websocket):
    await websocket.send(json.dumps({
        "id": 1,
        "cmd": "subscribe",
        "params": {"channels": ["ticker"]},
    }))


async def process_message(message: str, redis_client) -> Dict[str, Any] | None:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return None

    if data.get("type") != "ticker":
        return data

    msg = data.get("msg")
    if not msg or not isinstance(msg, dict):
        return data

    ticker = msg.get("market_ticker")
    if not ticker:
        return data

    if not is_allowed_market(ticker):
        return None

    analytics = compute_market_analytics(ticker, msg)

    tick = Tick(
        market=ticker,
        price=analytics["price"],
        bid=analytics["bid"],
        ask=analytics["ask"],
        spread=analytics["spread"],
        volume_1s=analytics["volume_1s"],
        volume_10s=analytics["volume_10s"],
        volume_60s=analytics["volume_60s"],
        imbalance=analytics["imbalance"],
        momentum=analytics["momentum"],
        last_trade_ts=analytics["last_trade_ts"],
        no_bid=analytics["no_bid"],
        no_ask=analytics["no_ask"],
        liquidity=analytics["liquidity"],
        open_interest=analytics["open_interest"],
        dollar_volume=analytics["dollar_volume"],
        dollar_open_interest=analytics["dollar_open_interest"],
        bid_size=analytics["bid_size"],
        ask_size=analytics["ask_size"],
        last_trade_size=analytics["last_trade_size"],
    )

    await redis_client.xadd("ticks", {"ticks": tick.model_dump_json()}, maxlen=10000)

    return {"type": "ticker", "msg": {**msg, **analytics}}


async def ws_loop(redis_client):
    headers = build_websocket_auth_headers()
    extra_headers = list(headers.items()) if headers else []
    print("beginning connection to ws")
    async with websockets.connect(
        WS_URL,
        additional_headers=extra_headers,
        ping_interval=20,
        ping_timeout=10,
        close_timeout=5,
    ) as websocket:
        print("Connected to Kalshi WebSocket")
        await subscribe_to_ticker(websocket)
        print("Subscribed to ticker")

        async for raw in websocket:
            try:
                parsed = await process_message(raw, redis_client)
                if parsed and parsed.get("type") == "ticker":
                    ticker = parsed.get("msg", {}).get("market_ticker")
                    price = parsed.get("msg", {}).get("price")
                    print("ticker:", ticker, price)
            except Exception as e:
                print("Error processing message:", e)
