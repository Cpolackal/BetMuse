import asyncio
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.crud import get_market, get_snapshots, search_markets, set_market
from app.db.session import get_db
from app.services.market_service import fetch_markets

router = APIRouter()


@router.get("/")
async def list_markets(limit: int = 1, cursor: str | None = None, db: Session = Depends(get_db)):
    data = await fetch_markets(cursor=cursor, limit=limit)
    markets = data.get("markets", []) if isinstance(data, dict) else []
    for market in markets:
        await asyncio.to_thread(set_market, db, market)
    return {"markets": markets}


@router.get("/search")
async def search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    markets = search_markets(db, q)
    return {
        "markets": [
            {
                "ticker": m.ticker,
                "title": m.title,
                "close_time": m.close_time,
                "result": m.result,
            }
            for m in markets
        ]
    }


@router.get("/{ticker}/snapshots")
async def market_snapshots(
    ticker: str,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    def _f(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else v

    rows = get_snapshots(db, ticker, limit)
    return {
        "ticker": ticker,
        "snapshots": [
            {
                "snapshot_time": r.snapshot_time,
                "last_price": _f(r.last_price),
                "yes_bid": _f(r.yes_bid),
                "yes_ask": _f(r.yes_ask),
                "no_bid": _f(r.no_bid),
                "no_ask": _f(r.no_ask),
                "spread": _f(r.spread),
                "imbalance": _f(r.imbalance),
                "momentum": _f(r.momentum),
                "volume_1s": r.volume_1s,
                "volume_10s": r.volume_10s,
                "volume_60s": r.volume_60s,
                "liquidity": _f(r.liquidity),
                "open_interest": _f(r.open_interest),
                "bid_size": _f(r.bid_size),
                "ask_size": _f(r.ask_size),
            }
            for r in rows
        ],
    }


@router.get("/{ticker}")
async def get_market_detail(ticker: str, db: Session = Depends(get_db)):
    market = get_market(db, ticker)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return {
        "ticker": market.ticker,
        "title": market.title,
        "event_ticker": market.event_ticker,
        "series_ticker": market.series_ticker,
        "open_time": market.open_time,
        "close_time": market.close_time,
        "result": market.result,
    }
