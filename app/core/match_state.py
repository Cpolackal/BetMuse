import json

from pydantic import BaseModel


class MatchState(BaseModel):
    """Normalized live-score state for one tennis match, provider-agnostic."""

    event_id: int
    home: str
    away: str
    tournament: str
    category: str
    best_of: int = 3
    status: str  # notstarted | inprogress | finished
    set_games: list[tuple[int, int]] = []  # games won per set, (home, away)
    points: tuple[str, str] = ("0", "0")  # current-game points, "A" = advantage
    serving: int | None = None  # 1 = home, 2 = away
    tiebreak: bool = False
    start_ts: int = 0
    updated_at: float = 0.0
    # In-play serve stats, carried forward across polls by score_feed's point
    # diffing. Index 0 = home serving, 1 = away serving. Tiebreak points are
    # out of scope (see score_feed._diff_game_point) and never counted here.
    serve_played: tuple[int, int] = (0, 0)
    serve_won: tuple[int, int] = (0, 0)

    def games_completed(self) -> int:
        return sum(h + a for h, a in self.set_games)

    def compact_json(self) -> str:
        """Small score-only snapshot for market_snapshots.score_state — the
        full model_dump_json() carries names/tournament, redundant per row."""
        return json.dumps({
            "set_games": self.set_games,
            "points": list(self.points),
            "serving": self.serving,
            "tiebreak": self.tiebreak,
            "status": self.status,
        })
