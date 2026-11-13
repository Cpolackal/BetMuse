from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String

from app.db.base import Base

# All timestamps are timezone-aware (timestamptz): comparisons against aware
# datetimes then don't depend on the Postgres session timezone.
TZDateTime = DateTime(timezone=True)


class market_meta(Base):
    __tablename__ = "market_meta"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True)
    event_ticker = Column(String, index=True)
    series_ticker = Column(String, index=True)
    title = Column(String)
    open_time = Column(TZDateTime)
    close_time = Column(TZDateTime)
    result = Column(Boolean, nullable=True)


class market_snapshots(Base):
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    snapshot_time = Column(TZDateTime, index=True)
    last_price = Column(Float)
    yes_bid = Column(Float)
    yes_ask = Column(Float)
    no_bid = Column(Float)
    no_ask = Column(Float)
    open_interest = Column(Float)
    liquidity = Column(Float)
    bid_size = Column(Float)
    ask_size = Column(Float)
    last_trade_size = Column(Float)
    last_trade_ts = Column(Float)
    spread = Column(Float)
    imbalance = Column(Float)
    momentum = Column(Float)
    volume_1s = Column(Integer)
    volume_10s = Column(Integer)
    volume_60s = Column(Integer)
    model_price = Column(Float, nullable=True)
    score_state = Column(String, nullable=True)


Index("ix_snapshots_ticker_time", market_snapshots.ticker, market_snapshots.snapshot_time)


class match_events(Base):
    __tablename__ = "match_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, index=True)
    ts = Column(TZDateTime, index=True)
    state_json = Column(String)


class market_links(Base):
    __tablename__ = "market_links"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True)
    event_id = Column(Integer, index=True)
    side = Column(Integer)
    home = Column(String)
    away = Column(String)
    linked_at = Column(TZDateTime)
