"""Data retention. See CLAUDE.md "Data Retention" for the open_time/close_time gotcha."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models.market import (
    market_links as MarketLink,
    market_meta as MarketMeta,
    market_snapshots as MarketSnapshot,
)

SNAPSHOT_MAX_AGE = timedelta(days=7)
RESOLVED_GRACE = timedelta(days=1)


def purge_snapshots(db: Session) -> int:
    """Safety-net purge for snapshots on markets that never resolve (stuck
    or orphaned) — resolved markets are removed entirely, meta and all, by
    purge_resolved_markets, well before this window matters."""
    cutoff = datetime.now(UTC) - SNAPSHOT_MAX_AGE
    result = db.execute(delete(MarketSnapshot).where(MarketSnapshot.snapshot_time < cutoff))
    db.commit()
    return result.rowcount


def purge_resolved_markets(db: Session) -> int:
    """Remove markets (and their snapshots/links) that have a known result and
    whose open_time is more than a day ago. Gated on open_time, not
    close_time: close_time is Kalshi's outer trading-window deadline (often
    ~2 weeks past the match), so gating on it would keep finished matches
    around that long. open_time is only a proxy for "the match is over" —
    trading opens hours to a day before play — but it is the one scheduling
    field we can rely on. Resolved markets with no open_time are never purged
    here. match_events are kept — they're keyed by tennis event, not Kalshi
    ticker, and stay useful for backtesting after the market itself is
    gone."""
    expired = (
        db.query(MarketMeta.ticker)
        .filter(MarketMeta.result.isnot(None))
        .filter(MarketMeta.open_time < datetime.now(UTC) - RESOLVED_GRACE)
        .scalar_subquery()
    )
    db.execute(delete(MarketSnapshot).where(MarketSnapshot.ticker.in_(expired)))
    db.execute(delete(MarketLink).where(MarketLink.ticker.in_(expired)))
    result = db.execute(delete(MarketMeta).where(MarketMeta.ticker.in_(expired)))
    db.commit()
    return result.rowcount
