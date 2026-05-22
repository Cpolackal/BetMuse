import asyncio

from pydantic import ValidationError
from app.core.contract_buffer import contract_buffer, Tick
from app.db.crud import set_market
from app.db.session import SessionLocal
from app.services.market_service import fetch_market


async def buffer_maintainer(redis_client, active_markets: dict):
    while True:
        result = await redis_client.xreadgroup(
            groupname="buffer_maintainer",
            consumername="buff-1",
            streams={"ticks": ">"},
            count=100,
            block=5000,
        )
        if not result:
            continue
        _, entries = result[0]
        for msg_id, fields in entries:
            try:
                ticked = Tick.model_validate_json(fields["ticks"])
                if ticked.market not in active_markets:
                    nxt = contract_buffer()
                    active_markets[ticked.market] = nxt
                    nxt.push(ticked)
                    ticker = ticked.market.removeprefix("market:")
                    market_data = await fetch_market(ticker)
                    if market_data:
                        db = SessionLocal()
                        try:
                            await asyncio.to_thread(set_market, db, market_data)
                        finally:
                            db.close()
                else:
                    active_markets[ticked.market].push(ticked)
            except ValidationError:
                pass
            await redis_client.xack("ticks", "buffer_maintainer", msg_id)
