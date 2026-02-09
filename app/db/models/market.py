from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from app.db.base import Base

class market(Base):
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key = "true", index = True)
    market_id = Column(String, index=True)
    ticker = Column(String, index=True)
    event_ticker = Column(String, index=True)
    timestamp = Column(DateTime)
    last_price = Column(Float)
    yes_bid = Column(Float)
    no_bid = Column(Float)
    yes_ask = Column(Float)
    no_ask = Column(Float)
    prev_yes = Column(Float)
    volume = Column(Float)
    open_interest = Column(Float)
    liquidity = Column(Float)
    result = Column(Boolean, nullable=True)
