"""DB access layer. Import from here; submodules are grouped by table/domain."""

from app.db.crud.markets import (
    get_completed_markets,
    get_market,
    get_unresolved_markets,
    get_upcoming_markets,
    resolve_market,
    search_markets,
    set_market,
)
from app.db.crud.retention import purge_resolved_markets, purge_snapshots
from app.db.crud.scores import get_all_market_links, insert_match_event, upsert_market_link
from app.db.crud.snapshots import bulk_insert_ticks, get_all_seeded_tickers, get_latest_prices, get_snapshots

__all__ = [
    "bulk_insert_ticks",
    "get_all_market_links",
    "get_all_seeded_tickers",
    "get_completed_markets",
    "get_latest_prices",
    "get_market",
    "get_snapshots",
    "get_unresolved_markets",
    "get_upcoming_markets",
    "insert_match_event",
    "purge_resolved_markets",
    "purge_snapshots",
    "resolve_market",
    "search_markets",
    "set_market",
    "upsert_market_link",
]
