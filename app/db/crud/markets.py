"""market_meta: ingest, lookup, search, resolution, and landing-page selection."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models.market import market_meta as MarketMeta
from app.services.match_mapper import ticker_date

# Candidates fetched per requested row before the Python-side date filter/sort.
CANDIDATE_MULTIPLIER = 6
MIN_CANDIDATES = 300

_TRUE_STRINGS = frozenset({"yes", "true", "1"})
_FALSE_STRINGS = frozenset({"no", "false", "0"})


def _parse_result(raw) -> bool | None:
    """Normalise Kalshi's `result` ("yes"/"no"/bool/"") to True/False/None."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return None


def get_market(db: Session, ticker: str):
    return db.query(MarketMeta).filter(MarketMeta.ticker == ticker).first()


def set_market(db: Session, market_obj: dict):
    """Insert a market's metadata if we haven't seen the ticker before."""
    ticker = market_obj.get("ticker")
    if not ticker or get_market(db, ticker):
        return
    event_ticker = market_obj.get("event_ticker")
    db.add(MarketMeta(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker=event_ticker.split("-")[0] if event_ticker else None,
        title=market_obj.get("title"),
        open_time=market_obj.get("open_time"),
        close_time=market_obj.get("close_time"),
        result=_parse_result(market_obj.get("result")),
    ))
    db.commit()


def resolve_market(db: Session, ticker: str, result: bool) -> bool:
    market = get_market(db, ticker)
    if not market:
        return False
    market.result = result
    db.commit()
    return True


def get_unresolved_markets(db: Session):
    """Markets backstop should check against Kalshi for a result. Gated on
    open_time, not close_time: close_time is Kalshi's outer trading-window
    deadline (often ~2 weeks past the match), so gating on it means a match
    that finished hours ago wouldn't even be checked until close_time arrives
    — result stays NULL indefinitely, and the match keeps showing up as
    "upcoming" (see get_upcoming_markets). 3h covers a slow best-of-5; a
    still-in-progress match's fetch just comes back empty and gets retried
    next cycle."""
    cutoff = datetime.now(UTC) - timedelta(hours=3)
    return (
        db.query(MarketMeta)
        .filter(MarketMeta.result.is_(None))
        .filter(MarketMeta.open_time.isnot(None))
        .filter(MarketMeta.open_time < cutoff)
        .all()
    )


def _dated_candidates(db: Session, limit: int, *, resolved: bool) -> list[tuple[MarketMeta, datetime | None]]:
    """Resolved or unresolved markets paired with their ticker-embedded match
    date (the only trustworthy per-match date we have — see
    get_upcoming_markets)."""
    result_filter = MarketMeta.result.isnot(None) if resolved else MarketMeta.result.is_(None)
    order = MarketMeta.open_time.desc() if resolved else MarketMeta.open_time.asc()
    rows = (
        db.query(MarketMeta)
        .filter(result_filter)
        .filter(MarketMeta.event_ticker.isnot(None))
        .order_by(order)
        .limit(max(limit * CANDIDATE_MULTIPLIER, MIN_CANDIDATES))
        .all()
    )
    return [(m, ticker_date(m.ticker)) for m in rows]


def get_upcoming_markets(db: Session, limit: int = 60) -> list:
    """Markets for matches that haven't concluded: not yet played, or
    played recently enough to plausibly still be in progress or awaiting
    resolution.

    Neither Kalshi timestamp on market_meta is a reliable "is the match
    still relevant" signal: close_time is the outer trading-window deadline
    (often ~2 weeks out), and open_time is when trading opens — which is
    *not* a fixed offset before the match; different tournaments open
    trading anywhere from a few hours to a full day ahead, so a cutoff on
    open_time either hides matches that are actually happening today (too
    strict) or keeps stale ones around (too loose). The ticker-embedded
    date (see match_mapper.ticker_date, also used for match_date display)
    tracks the actual scheduled match day directly, so filtering happens in
    Python against that instead of in SQL."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today - timedelta(days=1)
    dated = [(m, d) for m, d in _dated_candidates(db, limit, resolved=False) if d is not None and d >= cutoff]
    dated.sort(key=lambda pair: pair[1])
    return [m for m, _ in dated[:limit]]


def get_completed_markets(db: Session, limit: int = 40) -> list:
    """Recently resolved markets, most recently played first. Bounded by
    purge_resolved_markets, so no extra date filtering is needed here —
    ordering uses the ticker-embedded date (see get_upcoming_markets)."""
    dated = _dated_candidates(db, limit, resolved=True)
    dated.sort(key=lambda pair: pair[1] or datetime.min.replace(tzinfo=UTC), reverse=True)
    return [m for m, _ in dated[:limit]]


def search_markets(db: Session, q: str) -> list:
    """Resolved markets are kept until purge_resolved_markets removes them,
    so they're fine to surface as-is. Unresolved ones are excluded once their
    open_time is more than a day in the past — without this, a market
    backstop hasn't gotten to yet (or, historically, the close_time-gating
    bug — see get_unresolved_markets) would keep surfacing in search for as
    long as it sat unresolved, which was observed to be up to ~2 weeks."""
    cutoff = datetime.now(UTC) - timedelta(days=1)
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
