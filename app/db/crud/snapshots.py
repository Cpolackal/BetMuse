"""market_snapshots: the time-series written by db_writer and read by the API."""

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.contract_buffer import Tick
from app.db.models.market import market_snapshots as MarketSnapshot


def bulk_insert_ticks(
    db: Session,
    ticks: list[Tick],
    model_by_ticker: dict[str, float] | None = None,
    score_by_ticker: dict[str, str] | None = None,
):
    model_by_ticker = model_by_ticker or {}
    score_by_ticker = score_by_ticker or {}
    now = datetime.now(UTC)
    db.add_all([
        MarketSnapshot(
            ticker=tick.market,
            snapshot_time=now,
            last_price=tick.price,
            yes_bid=tick.bid,
            yes_ask=tick.ask,
            no_bid=tick.no_bid,
            no_ask=tick.no_ask,
            liquidity=tick.liquidity,
            open_interest=tick.open_interest,
            last_trade_ts=tick.last_trade_ts,
            bid_size=tick.bid_size,
            ask_size=tick.ask_size,
            last_trade_size=tick.last_trade_size,
            spread=tick.spread,
            imbalance=tick.imbalance,
            momentum=tick.momentum,
            volume_1s=tick.volume_1s,
            volume_10s=tick.volume_10s,
            volume_60s=tick.volume_60s,
            model_price=model_by_ticker.get(tick.market),
            score_state=score_by_ticker.get(tick.market),
        )
        for tick in ticks
    ])
    db.commit()


def get_snapshots(db: Session, ticker: str, limit: int = 200) -> list:
    """The newest `limit` snapshots for a ticker, oldest first."""
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.ticker == ticker)
        .order_by(MarketSnapshot.snapshot_time.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def get_latest_prices(db: Session, tickers: list[str]) -> dict[str, float]:
    """Most recent last_price per ticker (by insertion order)."""
    if not tickers:
        return {}
    latest_ids = (
        db.query(func.max(MarketSnapshot.id))
        .filter(MarketSnapshot.ticker.in_(tickers))
        .group_by(MarketSnapshot.ticker)
        .scalar_subquery()
    )
    rows = db.query(MarketSnapshot.ticker, MarketSnapshot.last_price).filter(MarketSnapshot.id.in_(latest_ids))
    return {ticker: price for ticker, price in rows}


def get_all_seeded_tickers(db: Session) -> list[str]:
    return [r[0] for r in db.query(MarketSnapshot.ticker).distinct().all()]
