from fastapi import Depends, APIRouter
from sqlalchemy.orm import Session
from app.services.market_service import fetch_markets
from app.db.crud import set_market
from app.db.session import get_db
from app.core.contract_buffer import Tick
import asyncio

router = APIRouter()


@router.get("/")
async def get_trades(limit: int = 1, cursor: str | None = None, db: Session = Depends(get_db)):
    """
    Fetch markets from the external Kalshi API and persist each market snapshot
    into the local database. Returns the raw markets payload.
    """
    data = await fetch_markets(cursor=cursor, limit=limit)

    # Kalshi API is expected to return a dict with a "markets" list
    markets = data.get("markets", []) if isinstance(data, dict) else []

    # Persist each market row in a threadpool so we don't block the event loop
    for market in markets:
        await asyncio.to_thread(set_market, db, market)

    return {"markets": markets}

