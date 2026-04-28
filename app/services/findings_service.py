import redis.asyncio as redis
import os
redis_client = redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)


# #       "price": price,
#         "bid": bid,
#         "ask": ask,
#         "spread": spread,
#         "volume_1s": int(vol_1s),
#         "volume_10s": int(vol_10s),
#         "volume_60s": int(vol_60s),
#         "momentum": momentum,
#         "imbalance": imbalance,
#         "last_trade_ts": int(ts),


async def compute_findings (ticker: str ) -> dict[str, any]:
    data = await redis_client.hgetall(f"market:{ticker}")
    if not data:
        return "No current data for that market."

    
