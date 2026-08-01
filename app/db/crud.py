from datetime import datetime, timezone

from sqlalchemy.orm import Session
from app.db.models.market import (
    market_meta as MarketMeta,
    market_snapshots as MarketSnapshot,
    match_events as MatchEvent,
    market_links as MarketLink,
)
from app.core.contract_buffer import Tick


def latest_snapshot(db: Session, ticker: str):
    return (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.ticker == ticker)
        .order_by(MarketSnapshot.id.desc())
        .first()
    )

def get_unresolved_markets(db: Session):
    from datetime import datetime, timezone
    return (
        db.query(MarketMeta)
        .filter(MarketMeta.result.is_(None))
        .filter(MarketMeta.close_time.isnot(None))
        .filter(MarketMeta.close_time < datetime.now(timezone.utc))
        .all()
    )

def set_market(db: Session, market_obj: dict):
    ticker = market_obj.get("ticker")
    if not ticker:
        return

    if db.query(MarketMeta).filter(MarketMeta.ticker == ticker).first():
        return

    raw_result = market_obj.get("result")
    if raw_result in ("", None):
        norm_result = None
    elif isinstance(raw_result, bool):
        norm_result = raw_result
    elif isinstance(raw_result, str):
        lowered = raw_result.lower()
        if lowered in ("yes", "true", "1"):
            norm_result = True
        elif lowered in ("no", "false", "0"):
            norm_result = False
        else:
            norm_result = None
    else:
        norm_result = None

    event_ticker = market_obj.get("event_ticker")
    series_ticker = event_ticker.split("-")[0] if event_ticker else None

    db.add(MarketMeta(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker=series_ticker,
        title=market_obj.get("title"),
        open_time=market_obj.get("open_time"),
        close_time=market_obj.get("close_time"),
        result=norm_result,
    ))
    db.commit()


def resolve_market(db: Session, ticker: str, result: bool) -> bool:
    market = db.query(MarketMeta).filter(MarketMeta.ticker == ticker).first()
    if not market:
        return False
    market.result = result
    db.commit()
    return True


def bulk_insert_ticks(
    db: Session,
    ticks: list[Tick],
    model_by_ticker: dict[str, float] | None = None,
    score_by_ticker: dict[str, str] | None = None,
):
    model_by_ticker = model_by_ticker or {}
    score_by_ticker = score_by_ticker or {}
    now = datetime.now(timezone.utc)
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


def insert_match_event(db: Session, event_id: int, ts: datetime, state_json: str):
    db.add(MatchEvent(event_id=event_id, ts=ts, state_json=state_json))
    db.commit()


def upsert_market_link(db: Session, ticker: str, event_id: int, side: int, home: str, away: str):
    link = db.query(MarketLink).filter(MarketLink.ticker == ticker).first()
    now = datetime.now(timezone.utc)
    if link:
        link.event_id = event_id
        link.side = side
        link.home = home
        link.away = away
        link.linked_at = now
    else:
        db.add(MarketLink(
            ticker=ticker, event_id=event_id, side=side, home=home, away=away, linked_at=now,
        ))
    db.commit()


def get_all_market_links(db: Session) -> list:
    return db.query(MarketLink).all()


def search_markets(db: Session, q: str) -> list:
    return (
        db.query(MarketMeta)
        .filter(MarketMeta.title.ilike(f"%{q}%"))
        .order_by(MarketMeta.close_time.desc())
        .limit(50)
        .all()
    )


def get_market(db: Session, ticker: str):
    return db.query(MarketMeta).filter(MarketMeta.ticker == ticker).first()


def purge_snapshots(db: Session) -> int:
    from sqlalchemy import text
    result = db.execute(text("""
        DELETE FROM market_snapshots
        WHERE snapshot_time < NOW() - INTERVAL '7 days'
        OR (
            snapshot_time < NOW() - INTERVAL '48 hours'
            AND ticker IN (
                SELECT ticker FROM market_meta WHERE result IS NOT NULL
            )
        )
    """))
    db.commit()
    return result.rowcount


def get_snapshots(db: Session, ticker: str, limit: int = 200) -> list:
    rows = (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.ticker == ticker)
        .order_by(MarketSnapshot.snapshot_time.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def get_all_seeded_tickers(db: Session) -> list[str]:
    rows = db.query(MarketSnapshot.ticker).distinct().all()
    return [r[0] for r in rows]

