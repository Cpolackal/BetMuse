from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from app.db.base import Base


class market_meta(Base):
    __tablename__ = "market_meta"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, unique=True, index=True)
    event_ticker = Column(String, index=True)
    title = Column(String)
    open_time = Column(DateTime)
    close_time = Column(DateTime)
    result = Column(Boolean, nullable=True)


class market_snapshots(Base):
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    last_price = Column(Float)
    yes_bid = Column(Float)
    no_bid = Column(Float)
    yes_ask = Column(Float)
    no_ask = Column(Float)
    volume_1s = Column(Float)
    volume_10s = Column(Float)
    volume_60s = Column(Float)
    open_interest = Column(Float)
    liquidity = Column(Float)
    spread = Column(Float)
    imbalance = Column(Float)
    momentum = Column(Float)
    last_trade_ts = Column(Float)
    bid_size = Column(Float)
    ask_size = Column(Float)
    last_trade_size = Column(Float)

