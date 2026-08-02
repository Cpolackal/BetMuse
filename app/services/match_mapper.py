import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Iterable, NamedTuple

from app.core.match_state import MatchState

# Kalshi title format: "Will {Full Name} win the {SurnameA} vs {SurnameB}: {Round} match?"
_TITLE_RE = re.compile(r"^Will (.+?) win the (.+?) vs (.+?): ")
# Ticker embeds the match date: KXATPMATCH-26JUL17RINTSI-RIN -> 2026-07-17
_TICKER_DATE_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})")
# Local start times can straddle the ticker's date depending on timezone.
DATE_TOLERANCE = timedelta(hours=36)


def _ascii(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()


def normalize_tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", _ascii(name).lower()) if len(t) > 1}


class ParsedTitle(NamedTuple):
    player_surname: set[str]  # normalized surname tokens of the market's player
    opponent_surname: set[str]
    query: str  # both surnames, accent-stripped, for the provider's event search


def player_full_name(title: str) -> str | None:
    """Extract the market's subject player's full name from the title —
    the one full name Kalshi's title format gives us (the other player only
    appears as a surname in the 'A vs B' clause)."""
    m = _TITLE_RE.match(title)
    return m.group(1) if m else None


def parse_title(title: str) -> ParsedTitle | None:
    m = _TITLE_RE.match(title)
    if not m:
        return None
    player, surname_a, surname_b = m.groups()
    player_tokens = normalize_tokens(player)
    a, b = normalize_tokens(surname_a), normalize_tokens(surname_b)
    if a and a <= player_tokens:
        mine, theirs = a, b
    elif b and b <= player_tokens:
        mine, theirs = b, a
    else:
        return None
    if not theirs:
        return None
    return ParsedTitle(mine, theirs, f"{_ascii(surname_a)} {_ascii(surname_b)}")


def _ticker_date(ticker: str) -> datetime | None:
    m = _TICKER_DATE_RE.search(ticker)
    if not m:
        return None
    try:
        return datetime.strptime(f"20{m.group(1)}{m.group(2)}{m.group(3)}", "%Y%b%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def select_event(
    parsed: ParsedTitle, candidates: Iterable[MatchState], ticker: str = ""
) -> tuple[int, int] | None:
    """Pick the one candidate event that matches the market and return
    (event_id, side), side 1 = home, 2 = away — the player whose win the
    market's YES contract pays on.

    Search results include historical head-to-heads, so the ticker-embedded
    date is the disambiguator; without one, only live/upcoming candidates
    count. Returns None on any ambiguity — an unmapped market just retries
    later, while a wrongly mapped one silently poisons downstream edge
    computation."""
    market_date = _ticker_date(ticker)

    matched: list[tuple[int, int]] = []
    for match in candidates:
        if market_date is not None:
            if not match.start_ts:
                continue
            start = datetime.fromtimestamp(match.start_ts, tz=timezone.utc)
            if abs(start - market_date) > DATE_TOLERANCE:
                continue
        elif match.status not in ("inprogress", "notstarted"):
            continue
        home_tokens, away_tokens = normalize_tokens(match.home), normalize_tokens(match.away)
        if parsed.player_surname <= home_tokens and parsed.opponent_surname <= away_tokens:
            matched.append((match.event_id, 1))
        elif parsed.player_surname <= away_tokens and parsed.opponent_surname <= home_tokens:
            matched.append((match.event_id, 2))

    return matched[0] if len(matched) == 1 else None
