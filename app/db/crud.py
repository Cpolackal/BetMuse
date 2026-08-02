from datetime import datetime, timedelta, timezone

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

def get_upcoming_markets(db: Session, limit: int = 60) -> list:
    """Markets for matches that haven't concluded: not yet started, or
    started recently enough to plausibly still be in progress.

    close_time is Kalshi's outer trading-window deadline (often ~2 weeks
    out for tennis) — not a signal the match itself is over — so it can't
    be used to exclude finished matches. open_time tracks the actual
    scheduled start far more closely; the 8h cutoff is generous enough to
    cover a slow best-of-5 without holding on to long-finished matches
    that are simply awaiting Kalshi's own resolution lag (see
    get_unresolved_markets)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=8)
    return (
        db.query(MarketMeta)
        .filter(MarketMeta.result.is_(None))
        .filter(MarketMeta.event_ticker.isnot(None))
        .filter(MarketMeta.open_time.isnot(None))
        .filter(MarketMeta.open_time > cutoff)
        .order_by(MarketMeta.open_time.asc())
        .limit(limit)
        .all()
    )


def get_latest_prices(db: Session, tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT DISTINCT ON (ticker) ticker, last_price
        FROM market_snapshots
        WHERE ticker = ANY(:tickers)
        ORDER BY ticker, id DESC
    """), {"tickers": tickers}).fetchall()
    return {r.ticker: r.last_price for r in rows}


def get_unresolved_markets(db: Session):
    """Markets backstop should check against Kalshi's historical API for a
    result. Gated on open_time, not close_time: close_time is Kalshi's
    outer trading-window deadline (often ~2 weeks past the match), so
    gating on it means a match that finished hours ago wouldn't even be
    checked until close_time arrives — result stays NULL indefinitely, and
    the match keeps showing up as "upcoming" (see get_upcoming_markets).
    3h covers a slow best-of-5; a still-in-progress match's fetch just
    comes back empty and gets retried next cycle."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    return (
        db.query(MarketMeta)
        .filter(MarketMeta.result.is_(None))
        .filter(MarketMeta.open_time.isnot(None))
        .filter(MarketMeta.open_time < cutoff)
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
    """Resolved markets are kept until purge_resolved_markets removes them
    (~1 day post-resolution), so they're fine to surface as-is. Unresolved
    ones are excluded once their open_time is more than a day in the past —
    without this, a market backstop hasn't gotten to yet (or, historically,
    the close_time-gating bug — see get_unresolved_markets) would keep
    surfacing in search for as long as it sat unresolved, which was
    observed to be up to ~2 weeks."""
    from sqlalchemy import or_
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    return (
        db.query(MarketMeta)
        .filter(MarketMeta.title.ilike(f"%{q}%"))
        .filter(or_(
            MarketMeta.result.isnot(None),
            MarketMeta.open_time.is_(None),
            MarketMeta.open_time > cutoff,
        ))
        .order_by(MarketMeta.open_time.desc())
        .limit(50)
        .all()
    )


def get_market(db: Session, ticker: str):
    return db.query(MarketMeta).filter(MarketMeta.ticker == ticker).first()


def purge_snapshots(db: Session) -> int:
    """Safety-net purge for snapshots on markets that never resolve (stuck
    or orphaned) — resolved markets are removed entirely, meta and all, by
    purge_resolved_markets below, well before this 7-day window matters."""
    from sqlalchemy import text
    result = db.execute(text("""
        DELETE FROM market_snapshots WHERE snapshot_time < NOW() - INTERVAL '7 days'
    """))
    db.commit()
    return result.rowcount


def purge_resolved_markets(db: Session) -> int:
    """Remove markets (and their snapshots/links) more than a day past
    close_time with a known result. match_events are kept — they're keyed by
    tennis event, not Kalshi ticker, and stay useful for backtesting after
    the market itself is gone."""
    from sqlalchemy import text
    cutoff = "result IS NOT NULL AND close_time < NOW() - INTERVAL '1 day'"
    db.execute(text(f"""
        DELETE FROM market_snapshots WHERE ticker IN (
            SELECT ticker FROM market_meta WHERE {cutoff}
        )
    """))
    db.execute(text(f"""
        DELETE FROM market_links WHERE ticker IN (
            SELECT ticker FROM market_meta WHERE {cutoff}
        )
    """))
    result = db.execute(text(f"DELETE FROM market_meta WHERE {cutoff}"))
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

