import asyncio
import os

import redis.asyncio as redis
from app.websockets.client import ws_loop
from app.workers.alert_engine import alert_engine
from app.workers.backstop import backstop
from app.workers.buffer_maintainer import buffer_maintainer
from app.workers.db_writer import db_writer


async def setup_stream(redis_client):
    groups = ["buffer_maintainer", "alert_engine"]
    for group in groups:
        try:
            await redis_client.xgroup_create("ticks", group, id="$", mkstream=True)
            print(f"Created group {group}")
        except Exception as e:
            if "BUSYGROUP" in str(e):
                print(f"Group {group} already exists")
            else:
                raise


async def run_websocket_client():
    active_markets = {}
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not set")
    redis_client = redis.from_url(redis_url, decode_responses=True)

    await setup_stream(redis_client)
    try:
        await asyncio.gather(
            ws_loop(redis_client),
            buffer_maintainer(redis_client, active_markets),
            alert_engine(redis_client),
            db_writer(active_markets),
            backstop(active_markets),
        )
    finally:
        await redis_client.aclose()
