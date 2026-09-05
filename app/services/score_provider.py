import os
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


def _current_server(first_to_serve: int | None) -> int | None:
    # Despite the name, SofaScore live-updates firstToServe every game to the
    # player serving the *current* game (verified empirically: it alternates
    # 1↔2 at each game boundary mid-set). So it's already the answer — any
    # extra parity math on top of it flips in lockstep with the field itself
    # and cancels out, freezing the derived server for the whole match.
    return first_to_serve if first_to_serve in (1, 2) else None


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
        serving=_current_server(event.get("firstToServe")),
        tiebreak=tiebreak,
        start_ts=event.get("startTimestamp", 0),
        updated_at=time.time(),
    )


class SofaScoreProvider:
    """Unofficial SofaScore live feed. Cloudflare blocks default TLS
    fingerprints, so requests must go through curl_cffi browser impersonation.
    Cloud/datacenter IPs (including AWS) also get IP-reputation challenge
    pages regardless of fingerprint, so requests are optionally routed
    through a residential proxy via SOFASCORE_PROXY_URL."""

    def __init__(self):
        self._session: AsyncSession | None = None

    def _get_session(self) -> AsyncSession:
        if self._session is None:
            proxy_url = os.getenv("SOFASCORE_PROXY_URL")
            proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
            self._session = AsyncSession(impersonate="chrome", proxies=proxies)
        return self._session

    async def fetch_live(self) -> list[MatchState]:
        session = self._get_session()
        resp = await session.get(SOFASCORE_LIVE_URL, timeout=10)
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
        session = self._get_session()
        resp = await session.get(SOFASCORE_SEARCH_URL.format(query=quote(query)), timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            parse_event(r["entity"])
            for r in results
            if "homeTeam" in r.get("entity", {}) and "id" in r.get("entity", {})
        ]
