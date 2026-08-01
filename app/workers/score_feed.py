import asyncio
import time

from app.core.match_state import MatchState
from app.db.crud import get_market
from app.db.session import SessionLocal
from app.services.match_mapper import parse_title, select_event
from app.services.score_provider import ScoreProvider, SofaScoreProvider

POLL_SECONDS = 5
MAP_RETRY_SECONDS = 60


def _fetch_title(ticker: str) -> str | None:
    db = SessionLocal()
    try:
        market = get_market(db, ticker)
        return market.title if market else None
    finally:
        db.close()


async def score_feed(
    redis_client,
    active_markets: dict,
    match_states: dict[int, MatchState],
    market_links: dict[str, tuple[int, int]],
    provider: ScoreProvider | None = None,
):
    """Polls the live-score provider, keeps `match_states` (event_id ->
    MatchState) current, and resolves market tickers in `active_markets` to
    (event_id, side) links in `market_links` by querying the provider's event
    search with both surnames from the Kalshi title. Links can resolve before
    a match goes live. Publishes state changes to the Redis stream `scores`
    for later backtesting."""
    provider = provider or SofaScoreProvider()
    last_map_attempt: dict[str, float] = {}
    last_published: dict[int, tuple] = {}
    was_live: set[int] = set()

    while True:
        try:
            live = await provider.fetch_live()
        except Exception as e:
            print(f"[score_feed] fetch failed: {e}")
            await asyncio.sleep(POLL_SECONDS)
            continue

        seen = set()
        for state in live:
            seen.add(state.event_id)
            was_live.add(state.event_id)
            match_states[state.event_id] = state
            fingerprint = (state.status, tuple(state.set_games), state.points, state.serving)
            if last_published.get(state.event_id) != fingerprint:
                last_published[state.event_id] = fingerprint
                await redis_client.xadd(
                    "scores",
                    {"event_id": str(state.event_id), "state": state.model_dump_json()},
                    maxlen=10000,
                )

        # A match that leaves the live feed is finished (or feed-dropped);
        # evict so stale scores are never joined against fresh ticks. Links
        # for matches that were never live (mapped pre-match) are kept.
        for event_id in list(match_states):
            if event_id not in seen:
                match_states.pop(event_id)
                last_published.pop(event_id, None)
        for ticker, (event_id, _) in list(market_links.items()):
            if event_id in was_live and event_id not in seen:
                market_links.pop(ticker)

        now = time.monotonic()
        for ticker in list(active_markets):
            if ticker in market_links:
                continue
            if now - last_map_attempt.get(ticker, 0) < MAP_RETRY_SECONDS:
                continue
            last_map_attempt[ticker] = now
            title = await asyncio.to_thread(_fetch_title, ticker)
            if not title:
                continue
            parsed = parse_title(title)
            if not parsed:
                continue
            try:
                candidates = await provider.search_events(parsed.query)
            except Exception as e:
                print(f"[score_feed] search failed for {ticker}: {e}")
                continue
            link = select_event(parsed, candidates, ticker=ticker)
            if link:
                market_links[ticker] = link
                print(f"[score_feed] mapped {ticker} -> event {link[0]} (side {link[1]})")

        await asyncio.sleep(POLL_SECONDS)
