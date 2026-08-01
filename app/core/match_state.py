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

    def games_completed(self) -> int:
        return sum(h + a for h, a in self.set_games)
