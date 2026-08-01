import asyncio

from app.core.live_state import market_links, match_states, model_prices
from app.db.crud import bulk_insert_ticks
from app.db.session import SessionLocal

SNAPSHOT_INTERVAL = 5  # seconds


async def db_writer(active_markets: dict):
    while True:
        await asyncio.sleep(SNAPSHOT_INTERVAL)
        if not active_markets:
            continue
        dirty = [
            buf for buf in active_markets.values()
            if buf.latest() is not None and buf.last_seen != buf.last_written
        ]
        if not dirty:
            continue

        ticks = [buf.latest() for buf in dirty]
        for buf in dirty:
            buf.last_written = buf.last_seen

        model_by_ticker: dict[str, float] = {}
        score_by_ticker: dict[str, str] = {}
        for tick in ticks:
            entry = model_prices.get(tick.market)
            if entry is not None:
                model_by_ticker[tick.market] = entry["model_price"]
            link = market_links.get(tick.market)
            state = match_states.get(link[0]) if link else None
            if state is not None:
                score_by_ticker[tick.market] = state.compact_json()

        db = SessionLocal()
        try:
            await asyncio.to_thread(bulk_insert_ticks, db, ticks, model_by_ticker, score_by_ticker)
        finally:
            db.close()
