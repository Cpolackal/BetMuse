import asyncio
import json
import os

import redis.asyncio as redis
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter()


def _parse_entry(msg_id: str, fields: dict) -> dict:
    entry = {
        "id": msg_id,
        "market": fields.get("market", ""),
        "type": fields.get("type", ""),
        "direction": fields.get("direction", ""),
        "value": float(fields.get("value", 0)),
        "ts": float(fields.get("ts", 0)),
    }
    # model_divergence alerts carry these extra fields (see alert_engine.py);
    # absent on every other alert type.
    if "model_price" in fields:
        entry["model_price"] = float(fields["model_price"])
    if "market_price" in fields:
        entry["market_price"] = float(fields["market_price"])
    return entry


async def _stream_generator(market: str | None):
    r = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)
    try:
        try:
            info = await r.xinfo_stream("alerts")
            last_id = info.get("last-generated-id", "0-0")
        except Exception:
            last_id = "0-0"

        while True:
            try:
                results = await r.xread({"alerts": last_id}, count=50, block=2000)
            except asyncio.CancelledError:
                break
            if results:
                _, entries = results[0]
                for msg_id, fields in entries:
                    last_id = msg_id
                    if market and fields.get("market") != market:
                        continue
                    payload = json.dumps(_parse_entry(msg_id, fields))
                    yield f"data: {payload}\n\n"
            else:
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        await r.aclose()


@router.get("/stream")
async def alert_stream(market: str | None = Query(default=None)):
    return StreamingResponse(
        _stream_generator(market),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
