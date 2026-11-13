"""Pure shaping of DB rows and live_state into the API payloads served by
``app/routes/markets``. No I/O here, so everything is unit-testable."""

import math
from collections.abc import Callable, Iterable
from typing import Any

from app.core.match_state import MatchState
from app.services.match_mapper import player_full_name, ticker_date


def clean_float(v):
    """JSON can't carry NaN; map it (and None) to None."""
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def group_into_matches(
    rows: Iterable,
    new_event: Callable[[Any], dict],
    player: Callable[[Any], dict],
    skip: Callable[[Any], bool] = lambda _row: False,
    limit: int | None = None,
) -> list[dict]:
    """Group market rows (one per player) by ``event_ticker`` into match dicts,
    keeping first-seen order and only events with exactly two players."""
    events: dict[str, dict] = {}
    for row in rows:
        if skip(row):
            continue
        event = events.get(row.event_ticker)
        if event is None:
            event = events[row.event_ticker] = new_event(row)
        event["players"].append(player(row))
    matches = [e for e in events.values() if len(e["players"]) == 2]
    return matches if limit is None else matches[:limit]


def links_by_event(market_links: dict[str, tuple[int, int]]) -> dict[int, list[tuple[str, int]]]:
    by_event: dict[int, list[tuple[str, int]]] = {}
    for ticker, (event_id, side) in market_links.items():
        by_event.setdefault(event_id, []).append((ticker, side))
    return by_event


def live_candidates(
    match_states: dict[int, MatchState], by_event: dict[int, list[tuple[str, int]]]
) -> list[tuple[int, MatchState, list[tuple[str, int]]]]:
    """Live matches that have at least one Kalshi market mapped."""
    return [(eid, st, by_event[eid]) for eid, st in match_states.items() if eid in by_event]


def build_live(candidates, prices: dict[str, float | None]) -> list[dict]:
    live = []
    for event_id, state, tickers in candidates:
        # Home side first: the live card indexes players[0] as home when it
        # attaches set scores, points, and the serve dot, and ticker iteration
        # order carries no such guarantee.
        players = [
            {"ticker": t, "name": state.home if side == 1 else state.away, "price": prices.get(t)}
            for t, side in sorted(tickers, key=lambda pair: pair[1])
        ]
        if len(players) != 2:
            continue
        live.append({
            "event_id": event_id,
            "home": state.home,
            "away": state.away,
            "tournament": state.tournament,
            "status": state.status,
            "set_games": state.set_games,
            "points": state.points,
            "serving": state.serving,
            "tiebreak": state.tiebreak,
            "players": players,
        })
    return live


def build_upcoming(rows, prices, market_links, live_event_ids: set[int], limit: int) -> list[dict]:
    """Unresolved matches not already shown as live."""

    def already_live(m) -> bool:
        link = market_links.get(m.ticker)
        return bool(link) and link[0] in live_event_ids

    return group_into_matches(
        rows,
        # open_time is when Kalshi opened trading — the one scheduling fact
        # about this match we can actually verify. The match's own start time
        # can't be, especially once a delay is in play (see
        # get_upcoming_markets), so we don't claim to know it here.
        new_event=lambda m: {"event_ticker": m.event_ticker, "open_time": m.open_time, "players": []},
        player=lambda m: {
            "ticker": m.ticker,
            "name": player_full_name(m.title) or m.title,
            "price": prices.get(m.ticker),
        },
        skip=already_live,
        limit=limit,
    )


def build_completed(rows, limit: int) -> list[dict]:
    return group_into_matches(
        rows,
        new_event=lambda m: {"event_ticker": m.event_ticker, "match_date": ticker_date(m.ticker), "players": []},
        player=lambda m: {
            "ticker": m.ticker,
            "name": player_full_name(m.title) or m.title,
            "won": m.result,
        },
        limit=limit,
    )


# Output order matters to nobody but keeps the JSON byte-identical to what the
# route returned before extraction. Volume counters are ints and never NaN.
SNAPSHOT_FIELDS = (
    "last_price", "yes_bid", "yes_ask", "no_bid", "no_ask", "spread", "imbalance", "momentum",
    "volume_1s", "volume_10s", "volume_60s",
    "liquidity", "open_interest", "bid_size", "ask_size", "model_price",
)
_INT_FIELDS = frozenset({"volume_1s", "volume_10s", "volume_60s"})


def snapshot_to_dict(row) -> dict:
    out = {"snapshot_time": row.snapshot_time}
    for f in SNAPSHOT_FIELDS:
        v = getattr(row, f)
        out[f] = v if f in _INT_FIELDS else clean_float(v)
    return out


def score_payload(link, state: MatchState | None, model: dict | None) -> dict:
    if link is None or state is None:
        return {"mapped": False}
    event_id, side = link
    model = model or {}
    return {
        "mapped": True,
        "event_id": event_id,
        "side": side,
        "home": state.home,
        "away": state.away,
        "tournament": state.tournament,
        "status": state.status,
        "best_of": state.best_of,
        "set_games": state.set_games,
        "points": state.points,
        "serving": state.serving,
        "tiebreak": state.tiebreak,
        "model_price": model.get("model_price"),
        "market_price": model.get("market_price"),
        "edge": model.get("edge"),
    }
