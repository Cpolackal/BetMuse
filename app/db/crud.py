from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.models.market import market_snapshots as MarketSnapshot
from app.core.contract_buffer import Tick


def prev_price(db: Session, ticker: str):
    return (
        db.query(MarketSnapshot)
        .filter(MarketSnapshot.ticker == ticker)
        .order_by(MarketSnapshot.id.desc())
        .first()
    )


def set_market(db: Session, market_obj: Tick):
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
        volume_60s=market_obj.get("volume_fp"),
        open_interest=market_obj.get("open_interest_fp"),
        liquidity=market_obj.get("liquidity_dollars"),
        result=norm_result,
    )

    db.add(db_market)
    db.commit()
    db.refresh(db_market)
    return db_market


def bulk_insert_ticks(db: Session, ticks: list[Tick]):
    tickers = {tick.market for tick in ticks}

    subq = (
        db.query(MarketSnapshot.ticker, func.max(MarketSnapshot.id).label("max_id"))
        .filter(MarketSnapshot.ticker.in_(tickers))
        .group_by(MarketSnapshot.ticker)
        .subquery()
    )
    prev_yes_map: dict[str, float] = {
        row.ticker: row.yes_bid
        for row in (
            db.query(MarketSnapshot.ticker, MarketSnapshot.yes_bid)
            .join(subq, MarketSnapshot.id == subq.c.max_id)
            .all()
        )
    }

    snapshots = []
    for tick in ticks:
        prev_yes = prev_yes_map.get(tick.market, tick.bid)
        snapshots.append(MarketSnapshot(
            ticker=tick.market,
            last_price=tick.price,
            yes_bid=tick.bid,
            yes_ask=tick.ask,
            no_bid=tick.no_bid,
            no_ask=tick.no_ask,
            liquidity=tick.liquidity,
            open_interest=tick.open_interest,
            volume_1s=tick.volume_1s,
            volume_10s=tick.volume_10s,
            volume_60s=tick.volume_60s,
            spread=tick.spread,
            imbalance=tick.imbalance,
            momentum=tick.momentum,
            last_trade_ts=tick.last_trade_ts,
            bid_size=tick.bid_size,
            ask_size=tick.ask_size,
            last_trade_size=tick.last_trade_size,
            prev_yes=prev_yes,
        ))
        prev_yes_map[tick.market] = tick.bid

    db.add_all(snapshots)
    db.commit()