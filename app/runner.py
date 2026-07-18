import asyncio
import logging
import os
import time

import redis.asyncio as redis
from app.websockets.client import ws_loop
from app.workers.alert_engine import alert_engine
from app.workers.backstop import backstop
from app.workers.buffer_maintainer import buffer_maintainer
from app.workers.db_writer import db_writer
from app.workers.score_feed import score_feed
from app.workers.seeder import seed_buffers

logger = logging.getLogger(__name__)

RESTART_BACKOFF_INITIAL = 1.0
RESTART_BACKOFF_MAX = 60.0
STABLE_RUN_SECONDS = 300  # a run this long resets the backoff


async def supervise(name: str, factory):
    """Run a worker coroutine forever, restarting it with backoff if it dies."""
    backoff = RESTART_BACKOFF_INITIAL
    while True:
        started = time.monotonic()
        try:
            await factory()
            logger.error("worker %s exited unexpectedly; restarting", name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker %s crashed; restarting in %.0fs", name, backoff)
        if time.monotonic() - started > STABLE_RUN_SECONDS:
            backoff = RESTART_BACKOFF_INITIAL
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, RESTART_BACKOFF_MAX)


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
    match_states = {}
    market_links = {}
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not set")
    redis_client = redis.from_url(redis_url, decode_responses=True)

    await setup_stream(redis_client)
    await seed_buffers(active_markets)
    try:
        await asyncio.gather(
            supervise("ws_loop", lambda: ws_loop(redis_client)),
            supervise("buffer_maintainer", lambda: buffer_maintainer(redis_client, active_markets)),
            supervise("alert_engine", lambda: alert_engine(redis_client)),
            supervise("db_writer", lambda: db_writer(active_markets)),
            supervise("backstop", lambda: backstop(active_markets)),
            supervise("score_feed", lambda: score_feed(redis_client, active_markets, match_states, market_links)),
        )
    finally:
        await redis_client.aclose()
