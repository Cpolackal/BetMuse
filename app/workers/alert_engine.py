import time
from app.core.contract_buffer import Tick
from pydantic import ValidationError
from app.services.detectors import microprice_delta

MIN_TICKS = 25
DELTA_THRESHOLD = 0.02
COOLDOWN_SECONDS = 30


async def alert_engine(redis_client, active_markets):
    last_alerted: dict[str, float] = {}

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
        for msg_id, fields in entries:
            try:
                ticked = Tick.model_validate_json(fields["ticks"])

                if ticked.market not in active_markets:
                    await redis_client.xack("ticks", "alert_engine", msg_id)
                    continue

                buf = active_markets[ticked.market]
                if buf.len() < MIN_TICKS:
                    await redis_client.xack("ticks", "alert_engine", msg_id)
                    continue

                now = time.monotonic()
                if now - last_alerted.get(ticked.market, 0) < COOLDOWN_SECONDS:
                    await redis_client.xack("ticks", "alert_engine", msg_id)
                    continue

                window = buf.tail(MIN_TICKS)
                delta = microprice_delta(window)

                if delta is not None and abs(delta) >= DELTA_THRESHOLD:
                    direction = "up" if delta > 0 else "down"
                    print(f"[ALERT] {ticked.market} microprice {direction} {delta:+.4f}")
                    last_alerted[ticked.market] = now

            except ValidationError:
                pass
            await redis_client.xack("ticks", "alert_engine", msg_id)

