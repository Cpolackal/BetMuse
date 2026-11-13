"""Score-feed persistence: match_events history and the ticker↔event links."""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models.market import market_links as MarketLink, match_events as MatchEvent


def insert_match_event(db: Session, event_id: int, ts: datetime, state_json: str):
    db.add(MatchEvent(event_id=event_id, ts=ts, state_json=state_json))
    db.commit()


def upsert_market_link(db: Session, ticker: str, event_id: int, side: int, home: str, away: str):
    values = {"event_id": event_id, "side": side, "home": home, "away": away, "linked_at": datetime.now(UTC)}
    stmt = insert(MarketLink).values(ticker=ticker, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=[MarketLink.ticker], set_=values))
    db.commit()


def get_all_market_links(db: Session) -> list:
    return db.query(MarketLink).all()
