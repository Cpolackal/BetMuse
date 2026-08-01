"""Process-wide live tennis state, shared between the runner's workers and
the FastAPI routes. Both run in the same process (see app/main.py), so a
module-level dict is sufficient — same pattern as `active_markets`."""

from app.core.match_state import MatchState

match_states: dict[int, MatchState] = {}
market_links: dict[str, tuple[int, int]] = {}
# ticker -> {"model_price": float, "market_price": float, "edge": float,
#            "pa": float, "pb": float, "ts": float}
model_prices: dict[str, dict] = {}
