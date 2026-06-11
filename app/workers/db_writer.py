import asyncio

from app.db.crud import bulk_insert_ticks
from app.db.session import SessionLocal

SNAPSHOT_INTERVAL = 10  # seconds


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

        db = SessionLocal()
        try:
            await asyncio.to_thread(bulk_insert_ticks, db, ticks)
        finally:
            db.close()
