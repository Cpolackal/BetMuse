import asyncio
import time
from datetime import datetime, timezone

from app.core.match_state import MatchState
from app.db.crud import get_all_market_links, get_market, insert_match_event, upsert_market_link
from app.db.session import SessionLocal
from app.services.match_mapper import parse_title, select_event
from app.services.score_provider import ScoreProvider, SofaScoreProvider

POLL_SECONDS = 5
MAP_RETRY_SECONDS = 60

_POINT_ORDER = {"0": 0, "15": 1, "30": 2, "40": 3}


def _diff_game_point(old_pts: tuple[str, str], new_pts: tuple[str, str]) -> int | None:
    """Return 1 if home won the point, 2 if away did, or None if the pair
    isn't a valid single-point step (handles the deuce/advantage loop, which
    isn't a simple ordinal increment)."""
    oh, oa = old_pts
    nh, na = new_pts
    if oh == "40" and oa == "40":
        if nh == "A" and na == "40":
            return 1
        if nh == "40" and na == "A":
            return 2
        return None
    if oh == "A":
        return 2 if (nh == "40" and na == "40") else None
    if oa == "A":
        return 1 if (nh == "40" and na == "40") else None
    if oh in _POINT_ORDER and oa in _POINT_ORDER and nh in _POINT_ORDER and na in _POINT_ORDER:
        if _POINT_ORDER[nh] == _POINT_ORDER[oh] + 1 and na == oa:
            return 1
        if _POINT_ORDER[na] == _POINT_ORDER[oa] + 1 and nh == oh:
            return 2
    return None


def _diff_point(old: MatchState, new: MatchState) -> int | None:
    """Return 1/2 for who won the next point between two consecutive polls
    of the same match, or None when the gap can't be attributed to a single,
    unambiguous point: the game or set advanced (multiple points elapsed, or
    this poll missed the game-ending point), the server changed, or either
    side is mid-tiebreak (tiebreak point tracking is out of scope — the
    5s poll cadence makes attributing tiebreak points to a server unreliable
    without also modeling the mid-breaker rotation)."""
    if old.tiebreak or new.tiebreak:
        return None
    if old.set_games != new.set_games or old.serving != new.serving:
        return None
    if old.serving not in (1, 2):
        return None
    return _diff_game_point(old.points, new.points)


def _merge_serve_stats(prev: MatchState | None, new: MatchState) -> MatchState:
    """Carry forward accumulated serve counters and, when the poll gap is an
    unambiguous single point, credit it to whoever was serving."""
    if prev is None:
        return new
    played = list(prev.serve_played)
    won = list(prev.serve_won)
    winner = _diff_point(prev, new)
    if winner is not None:
        server_idx = prev.serving - 1
        played[server_idx] += 1
        if winner == prev.serving:
            won[server_idx] += 1
    return new.model_copy(update={"serve_played": tuple(played), "serve_won": tuple(won)})


def _fetch_title(ticker: str) -> str | None:
    db = SessionLocal()
    try:
        market = get_market(db, ticker)
        return market.title if market else None
    finally:
        db.close()


def _insert_match_event(event_id: int, state: MatchState) -> None:
    db = SessionLocal()
    try:
        insert_match_event(db, event_id, datetime.now(timezone.utc), state.compact_json())
    finally:
        db.close()


def _upsert_link(ticker: str, event_id: int, side: int, home: str, away: str) -> None:
    db = SessionLocal()
    try:
        upsert_market_link(db, ticker, event_id, side, home, away)
    finally:
        db.close()


def _preload_links(tickers: set[str]) -> dict[str, tuple[int, int]]:
    """Restore ticker->(event_id, side) links persisted by prior runs, scoped
    to markets that are still active — a link for a market that's since
    closed would just be dead weight."""
    db = SessionLocal()
    try:
        return {
            row.ticker: (row.event_id, row.side)
            for row in get_all_market_links(db)
            if row.ticker in tickers
        }
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

    preloaded = await asyncio.to_thread(_preload_links, set(active_markets))
    for ticker, link in preloaded.items():
        market_links.setdefault(ticker, link)
    if preloaded:
        print(f"[score_feed] preloaded {len(preloaded)} market link(s) from db")

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
            state = _merge_serve_stats(match_states.get(state.event_id), state)
            match_states[state.event_id] = state
            fingerprint = (state.status, tuple(state.set_games), state.points, state.serving)
            if last_published.get(state.event_id) != fingerprint:
                last_published[state.event_id] = fingerprint
                await redis_client.xadd(
                    "scores",
                    {"event_id": str(state.event_id), "state": state.model_dump_json()},
                    maxlen=10000,
                )
                await asyncio.to_thread(_insert_match_event, state.event_id, state)

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
                event_id, side = link
                matched = next((c for c in candidates if c.event_id == event_id), None)
                home, away = (matched.home, matched.away) if matched else ("", "")
                await asyncio.to_thread(_upsert_link, ticker, event_id, side, home, away)
                print(f"[score_feed] mapped {ticker} -> event {link[0]} (side {link[1]})")

        await asyncio.sleep(POLL_SECONDS)
