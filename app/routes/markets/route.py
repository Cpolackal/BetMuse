import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.live_state import market_links, match_states, model_prices
from app.core.market_filter import is_allowed_market
from app.db.crud import (
    get_completed_markets,
    get_latest_prices,
    get_market,
    get_snapshots,
    get_upcoming_markets,
    search_markets,
    set_market,
)
from app.db.session import get_db
from app.kalshi.rest import fetch_markets
from app.services import landing_page

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
    # Live comes straight from SofaScore's live response (live_state.match_states),
    # refreshed every 5s, so it can't go stale the way a database reading could.
    # live_total counts every live ATP match SofaScore reports, mapped to a
    # Kalshi market or not, so the frontend can tell "nothing is being played"
    # from "matches are live, just not mapped yet".
    candidates = landing_page.live_candidates(match_states, landing_page.links_by_event(market_links))
    live_tickers = [t for _, _, tickers in candidates for t, _ in tickers]
    live_prices = await asyncio.to_thread(get_latest_prices, db, live_tickers)
    live = landing_page.build_live(candidates, live_prices)
    live_event_ids = {m["event_id"] for m in live}

    rows = await asyncio.to_thread(get_upcoming_markets, db, limit * 3)
    prices = await asyncio.to_thread(get_latest_prices, db, [m.ticker for m in rows])
    upcoming = landing_page.build_upcoming(rows, prices, market_links, live_event_ids, limit)

    completed_rows = await asyncio.to_thread(get_completed_markets, db, limit)
    completed = landing_page.build_completed(completed_rows, limit)

    return {"live": live, "live_total": len(match_states), "upcoming": upcoming, "completed": completed}


@router.get("/{ticker}/snapshots")
async def market_snapshots(
    ticker: str,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    rows = await asyncio.to_thread(get_snapshots, db, ticker, limit)
    return {"ticker": ticker, "snapshots": [landing_page.snapshot_to_dict(r) for r in rows]}


@router.get("/{ticker}/score")
async def market_score(ticker: str):
    link = market_links.get(ticker)
    state = match_states.get(link[0]) if link else None
    return landing_page.score_payload(link, state, model_prices.get(ticker))


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
