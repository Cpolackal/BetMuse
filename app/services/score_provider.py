import time
from typing import Any, Protocol
from urllib.parse import quote

from curl_cffi.requests import AsyncSession

from app.core.match_state import MatchState

# Kalshi KXATPMATCH markets are ATP tour-level matches only.
ALLOWED_CATEGORIES = {"atp"}

GRAND_SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")

SOFASCORE_LIVE_URL = "https://api.sofascore.com/api/v1/sport/tennis/events/live"
SOFASCORE_SEARCH_URL = "https://api.sofascore.com/api/v1/search/events?q={query}"


class ScoreProvider(Protocol):
    async def fetch_live(self) -> list[MatchState]: ...

    async def search_events(self, query: str) -> list[MatchState]: ...


def _current_server(first_to_serve: int | None, games_completed: int,
                    tiebreak: bool, points: tuple[str, str]) -> int | None:
    if first_to_serve not in (1, 2):
        return None
    # Serve alternates every game; total completed games gives parity. This
    # also holds across a tiebreak set boundary (the TB counts as one game and
    # the post-TB serve rule matches simple alternation).
    server = first_to_serve if games_completed % 2 == 0 else 3 - first_to_serve
    if tiebreak:
        # Within a tiebreak serve changes after the 1st point, then every 2.
        try:
            played = int(points[0]) + int(points[1])
        except ValueError:
            return server
        if (played + 1) // 2 % 2 == 1:
            server = 3 - server
    return server


def parse_event(event: dict[str, Any]) -> MatchState:
    home_score = event.get("homeScore", {})
    away_score = event.get("awayScore", {})

    set_games: list[tuple[int, int]] = []
    for n in range(1, 6):
        h, a = home_score.get(f"period{n}"), away_score.get(f"period{n}")
        if h is None and a is None:
            break
        set_games.append((h or 0, a or 0))

    points = (str(home_score.get("point", "0")), str(away_score.get("point", "0")))
    tiebreak = bool(set_games) and set_games[-1][0] == 6 and set_games[-1][1] == 6
    games_completed = sum(h + a for h, a in set_games)

    tournament = event.get("tournament", {}).get("name", "")
    best_of = 5 if any(s in tournament.lower() for s in GRAND_SLAMS) else 3

    return MatchState(
        event_id=event["id"],
        home=event.get("homeTeam", {}).get("name", ""),
        away=event.get("awayTeam", {}).get("name", ""),
        tournament=tournament,
        category=event.get("tournament", {}).get("category", {}).get("slug", ""),
        best_of=best_of,
        status=event.get("status", {}).get("type", "unknown"),
        set_games=set_games,
        points=points,
        serving=_current_server(event.get("firstToServe"), games_completed, tiebreak, points),
        tiebreak=tiebreak,
        start_ts=event.get("startTimestamp", 0),
        updated_at=time.time(),
    )


class SofaScoreProvider:
    """Unofficial SofaScore live feed. Cloudflare blocks default TLS
    fingerprints, so requests must go through curl_cffi browser impersonation."""

    def __init__(self):
        self._session: AsyncSession | None = None

    async def fetch_live(self) -> list[MatchState]:
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome")
        resp = await self._session.get(SOFASCORE_LIVE_URL, timeout=10)
        resp.raise_for_status()
        events = resp.json().get("events", [])
        return [
            parse_event(e)
            for e in events
            if e.get("tournament", {}).get("category", {}).get("slug") in ALLOWED_CATEGORIES
        ]

    async def search_events(self, query: str) -> list[MatchState]:
        """Search events by free text (e.g. both surnames). SofaScore's own
        search does the name resolution — accents, transliteration, aliases —
        so callers only need to verify the result, not fuzzy-match it."""
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome")
        resp = await self._session.get(SOFASCORE_SEARCH_URL.format(query=quote(query)), timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            parse_event(r["entity"])
            for r in results
            if "homeTeam" in r.get("entity", {}) and "id" in r.get("entity", {})
        ]
