from app.core.contract_buffer import contract_buffer, Tick
from app.db.crud import latest_snapshot
from pydantic import ValidationError
from app.db.session import SessionLocal


async def alert_engine(redis_client):
    while True:
        result = await redis_client.xreadgroup(
            groupname="alert_engine",
            consumername="alt-1",
            streams={"ticks": ">"},
            count=100,
            block=5000,
        )
        if not result:
            continue
        _, entries = result[0]

            
