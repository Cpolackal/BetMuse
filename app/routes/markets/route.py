import asyncio
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.live_state import market_links, match_states, model_prices
from app.core.market_filter import is_allowed_market
from app.db.crud import (
    get_latest_prices,
    get_market,
    get_snapshots,
    get_upcoming_markets,
    search_markets,
    set_market,
)
from app.db.session import get_db
from app.services.market_service import fetch_markets
from app.services.match_mapper import player_full_name

router = APIRouter()


@router.get("/")
async def list_markets(limit: int = 1, cursor: str | None = None, db: Session = Depends(get_db)):
    data = await fetch_markets(cursor=cursor, limit=limit)
    markets = data.get("markets", []) if isinstance(data, dict) else []
    markets = [m for m in markets if is_allowed_market(m.get("ticker", ""))]
    for market in markets:
        await asyncio.to_thread(set_market, db, market)
    return {"markets": markets}


@router.get("/search")
async def search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    markets = await asyncio.to_thread(search_markets, db, q)
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


@router.get("/upcoming")
async def upcoming_matches(limit: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    rows = await asyncio.to_thread(get_upcoming_markets, db, limit * 3)
    prices = await asyncio.to_thread(get_latest_prices, db, [m.ticker for m in rows])

    events: dict[str, dict] = {}
    order: list[str] = []
    for m in rows:
        key = m.event_ticker
        ev = events.get(key)
        if ev is None:
            ev = {"event_ticker": key, "open_time": m.open_time, "close_time": m.close_time, "players": []}
            events[key] = ev
            order.append(key)
        ev["players"].append({
            "ticker": m.ticker,
            "name": player_full_name(m.title) or m.title,
            "price": prices.get(m.ticker),
        })

    matches = [events[k] for k in order if len(events[k]["players"]) == 2][:limit]
    return {"matches": matches}


@router.get("/{ticker}/snapshots")
async def market_snapshots(
    ticker: str,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    def _f(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else v

    rows = await asyncio.to_thread(get_snapshots, db, ticker, limit)
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
                "model_price": _f(r.model_price),
            }
            for r in rows
        ],
    }


@router.get("/{ticker}/score")
async def market_score(ticker: str):
    link = market_links.get(ticker)
    state = match_states.get(link[0]) if link else None
    if link is None or state is None:
        return {"mapped": False}

    event_id, side = link
    model = model_prices.get(ticker)
    return {
        "mapped": True,
        "event_id": event_id,
        "side": side,
        "home": state.home,
        "away": state.away,
        "tournament": state.tournament,
        "status": state.status,
        "best_of": state.best_of,
        "set_games": state.set_games,
        "points": state.points,
        "serving": state.serving,
        "tiebreak": state.tiebreak,
        "model_price": model.get("model_price") if model else None,
        "market_price": model.get("market_price") if model else None,
        "edge": model.get("edge") if model else None,
    }


@router.get("/{ticker}")
async def get_market_detail(ticker: str, db: Session = Depends(get_db)):
    market = await asyncio.to_thread(get_market, db, ticker)
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
