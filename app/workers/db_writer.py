from collections import deque

from pydantic import ValidationError
from app.core.contract_buffer import Tick
from app.db.crud import bulk_insert_ticks
from app.db.session import SessionLocal

BATCH_SIZE = 100


async def db_writer(redis_client, dblist: deque[Tick]):
    while True:
        result = await redis_client.xreadgroup(
            groupname="db_writer",
            consumername="db-1",
            streams={"ticks": ">"},
            count=100,
            block=5000,
        )
        if not result:
            continue
        _, entries = result[0]
        ack_ids = []
        for msg_id, fields in entries:
            try:
                ticked = Tick.model_validate_json(fields["ticks"])
                dblist.append(ticked)
            except ValidationError:
                pass
            ack_ids.append(msg_id)

        if ack_ids:
            await redis_client.xack("ticks", "db_writer", *ack_ids)

        while len(dblist) >= BATCH_SIZE:
            batch = [dblist.popleft() for _ in range(BATCH_SIZE)]
            db = SessionLocal()
            try:
                bulk_insert_ticks(db, batch)
            finally:
                db.close()
