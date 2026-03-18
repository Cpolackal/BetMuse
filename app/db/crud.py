from sqlalchemy.orm import Session
from app.db.models.market import market_snapshots as MarketSnapshot


def get_market(db: Session, id: int):
    return db.get(MarketSnapshot, id)


def prev_price(db: Session, ticker: str):
    return (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.ticker == ticker)
        .order_by(MarketSnapshot.id.desc())
        .first()
    )


def set_market(db: Session, market_obj: dict):
    """
    Persist a single market snapshot from the external API response.
    `market_obj` is expected to be a dict from the Kalshi API.
    """
    ticker = market_obj.get("ticker")

    # Normalize result to a proper boolean / NULL for the DB
    raw_result = market_obj.get("result")
    if raw_result in ("", None):
        norm_result = None
    elif isinstance(raw_result, bool):
        norm_result = raw_result
    elif isinstance(raw_result, str):
        # Map common string values to booleans; otherwise store NULL
        lowered = raw_result.lower()
        if lowered in ("yes", "true", "1"):
            norm_result = True
        elif lowered in ("no", "false", "0"):
            norm_result = False
        else:
            norm_result = None
    else:
        norm_result = None
    prev_snapshot = prev_price(db, ticker) if ticker else None
    prev_yes = prev_snapshot.yes_bid if prev_snapshot else None

    db_market = MarketSnapshot(
        ticker=ticker,
        event_ticker=market_obj.get("event_ticker"),
        title=market_obj.get("title"),
        open_time=market_obj.get("open_time"),
        close_time=market_obj.get("close_time"),
        # Kalshi uses *_dollars / *_fp fields; map them into our columns
        last_price=market_obj.get("last_price_dollars"),
        yes_bid=market_obj.get("yes_bid_dollars"),
        yes_ask=market_obj.get("yes_ask_dollars"),
        no_bid=market_obj.get("no_bid_dollars"),
        no_ask=market_obj.get("no_ask_dollars"),
        prev_yes=prev_yes,
        volume=market_obj.get("volume_fp"),
        open_interest=market_obj.get("open_interest_fp"),
        liquidity=market_obj.get("liquidity_dollars"),
        result=norm_result,
    )

    db.add(db_market)
    db.commit()
    db.refresh(db_market)
    return db_market