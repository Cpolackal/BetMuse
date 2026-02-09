from fastapi import APIRouter
from app.services.market_service import fetch_markets

router = APIRouter()

@router.get("/")
async def get_trades(limit: int = 100, cursor: str | None = None):
    return await fetch_markets(cursor=cursor, limit=limit)