import httpx


async def fetch_markets(cursor, limit = 100):
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor

    async with httpx.AsyncClient(timeout = 10) as client:
        response = await client.get(
            "https://api.elections.kalshi.com/trade-api/v2/markets", 
            params=params
            )
        data = response.json()
        return data
        

