import httpx

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
HIST_URL = "https://external-api.kalshi.com/trade-api/v2/historical"

async def fetch_markets(cursor, limit = 100):
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{BASE_URL}/markets", params=params)
        return response.json()


async def fetch_market(ticker: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{BASE_URL}/markets/{ticker}")
        if response.status_code != 200:
            return None
        return response.json().get("market")
    
async def fetch_closed_market(ticker: str) -> dict | None:
    async with httpx.AsyncClient(timeout = 10) as client:
        response = await client.get(f"{HIST_URL}/markets/{ticker}")
        if response.status_code != 200:
            return None
        return response.json().get("market")
        

