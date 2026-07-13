import asyncio

from app.core.contract_buffer import Tick, contract_buffer
from app.core.market_filter import is_allowed_market
from app.db.crud import get_all_seeded_tickers, get_snapshots
from app.db.session import SessionLocal

SEED_LIMIT = 600


def _snapshot_to_tick(row) -> Tick:
    return Tick(
        market=row.ticker,
        price=row.last_price or 0.0,
        bid=row.yes_bid or 0.0,
        ask=row.yes_ask or 0.0,
        spread=row.spread or 0.0,
        volume_1s=row.volume_1s or 0,
        volume_10s=row.volume_10s or 0,
        volume_60s=row.volume_60s or 0,
        imbalance=row.imbalance or 0.0,
        momentum=row.momentum or 0.0,
        last_trade_ts=int(row.last_trade_ts or 0),
        no_bid=row.no_bid,
        no_ask=row.no_ask,
        liquidity=row.liquidity,
        open_interest=row.open_interest,
        bid_size=row.bid_size,
        ask_size=row.ask_size,
        last_trade_size=row.last_trade_size,
    )


def _load_from_db() -> dict[str, contract_buffer]:
    db = SessionLocal()
    try:
        tickers = get_all_seeded_tickers(db)
        buffers: dict[str, contract_buffer] = {}
        for ticker in tickers:
            if not is_allowed_market(ticker):
                continue
            rows = get_snapshots(db, ticker, limit=SEED_LIMIT)
            if not rows:
                continue
            buf = contract_buffer()
            for row in rows:
                buf.push(_snapshot_to_tick(row))
            buf.last_written = buf.last_seen
            buffers[ticker] = buf
        return buffers
    finally:
        db.close()


async def seed_buffers(active_markets: dict) -> None:
    buffers = await asyncio.to_thread(_load_from_db)
    for ticker, buf in buffers.items():
        if ticker not in active_markets:
            active_markets[ticker] = buf
    if buffers:
        print(f"[seeder] seeded {len(buffers)} markets from DB")
    else:
        print("[seeder] no existing snapshots — starting cold")
