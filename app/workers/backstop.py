import asyncio
import logging
import time

from app.db.crud import get_unresolved_markets, resolve_market, purge_snapshots
from app.db.session import SessionLocal
from app.services.market_service import fetch_closed_market

logger = logging.getLogger(__name__)

INTERVAL = 1800
STALE_AFTER = 3600  # evict buffers idle for >1 hour


def _normalize_result(raw) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.lower()
        if lowered in ("yes", "true", "1"):
            return True
        if lowered in ("no", "false", "0"):
            return False
    return None


async def backstop(active_markets: dict):
    while True:
        await asyncio.sleep(INTERVAL)

        db = SessionLocal()
        try:
            to_check = get_unresolved_markets(db)
            if to_check:
                logger.info("backstop: checking %d unresolved markets", len(to_check))
                for market in to_check:
                    try:
                        market_data = await fetch_closed_market(market.ticker)
                        if not market_data:
                            continue
                        resolved = _normalize_result(market_data.get("result"))
                        if resolved is None:
                            continue
                        resolve_market(db, market.ticker, resolved)
                        active_markets.pop(market.ticker, None)
                        logger.info("backstop: resolved %s → %s", market.ticker, resolved)
                    except Exception:
                        logger.exception("backstop: error processing %s", market.ticker)
        except Exception:
            logger.exception("backstop: db error")
        finally:
            db.close()

        now = time.monotonic()
        stale = [t for t, buf in active_markets.items() if now - buf.last_seen > STALE_AFTER]
        for ticker in stale:
            active_markets.pop(ticker, None)
            logger.info("backstop: evicted stale buffer %s", ticker)
        if stale:
            logger.info("backstop: evicted %d stale buffers", len(stale))

        db = SessionLocal()
        try:
            deleted = purge_snapshots(db)
            if deleted:
                logger.info("backstop: purged %d stale snapshots", deleted)
        except Exception:
            logger.exception("backstop: error during snapshot purge")
        finally:
            db.close()
