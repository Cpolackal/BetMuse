"""Closed-form tennis win-probability model (O'Malley / Barnett-Clarke).

Everything is computed from two parameters: pa = P(home wins a point on home
serve), pb = P(away wins a point on away serve). All probabilities returned
are from the home player's perspective. Assumes a 7-point tiebreak at 6-6 in
every set (no 10-point final-set breakers).
"""

from functools import lru_cache

from app.core.match_state import MatchState

POINT_MAP = {"0": 0, "15": 1, "30": 2, "40": 3, "A": 4}

# Tour-average point-win rate on serve; calibration skews around this.
BASE_SERVE_WIN = 0.645
MAX_SKEW = 0.2


@lru_cache(maxsize=None)
def game_win_prob(p: float, a: int = 0, b: int = 0) -> float:
    """P(server wins the game) from server points a, receiver points b."""
    if a >= 4 and a - b >= 2:
        return 1.0
    if b >= 4 and b - a >= 2:
        return 0.0
    q = 1 - p
    if a >= 3 and b >= 3:
        deuce = p * p / (1 - 2 * p * q)
        if a == b:
            return deuce
        return p + q * deuce if a > b else p * deuce
    return p * game_win_prob(p, a + 1, b) + q * game_win_prob(p, a, b + 1)


def _tb_point_server(first: int, points_played: int) -> int:
    # Tiebreak rotation: first server serves point 1, then two each.
    return first if ((points_played + 1) // 2) % 2 == 0 else 3 - first


@lru_cache(maxsize=None)
def tb_win_prob(pa: float, pb: float, a: int, b: int, first: int) -> float:
    """P(home wins the tiebreak) from points (a, b); `first` served point 1."""
    if a >= 7 and a - b >= 2:
        return 1.0
    if b >= 7 and b - a >= 2:
        return 0.0
    if a >= 6 and a == b:
        # From any level score >= 6-6 the next two points are one on each
        # serve, so win-by-2 has a closed form.
        w = pa * (1 - pb)
        l = (1 - pa) * pb
        return w / (w + l)
    server = _tb_point_server(first, a + b)
    ph = pa if server == 1 else 1 - pb
    return ph * tb_win_prob(pa, pb, a + 1, b, first) + (1 - ph) * tb_win_prob(pa, pb, a, b + 1, first)


@lru_cache(maxsize=None)
def set_win_prob(pa: float, pb: float, ga: int, gb: int, server: int) -> float:
    """P(home wins the set) from games (ga, gb); `server` serves next game."""
    if ga == 6 and gb == 6:
        return tb_win_prob(pa, pb, 0, 0, server)
    if ga == 7 or (ga >= 6 and ga - gb >= 2):
        return 1.0
    if gb == 7 or (gb >= 6 and gb - ga >= 2):
        return 0.0
    hold = game_win_prob(pa if server == 1 else pb, 0, 0)
    ph = hold if server == 1 else 1 - hold
    return ph * set_win_prob(pa, pb, ga + 1, gb, 3 - server) + (1 - ph) * set_win_prob(
        pa, pb, ga, gb + 1, 3 - server
    )


@lru_cache(maxsize=None)
def match_from_sets(pa: float, pb: float, sh: int, sa: int, best_of: int) -> float:
    """P(home wins match) given sets won (sh, sa), fresh sets ahead. Who
    serves first in a future set is unknowable pre-set; the two cases differ
    negligibly, so use their average."""
    need = best_of // 2 + 1
    if sh >= need:
        return 1.0
    if sa >= need:
        return 0.0
    s = (set_win_prob(pa, pb, 0, 0, 1) + set_win_prob(pa, pb, 0, 0, 2)) / 2
    return s * match_from_sets(pa, pb, sh + 1, sa, best_of) + (1 - s) * match_from_sets(
        pa, pb, sh, sa + 1, best_of
    )


def _set_complete(h: int, a: int) -> bool:
    return h == 7 or a == 7 or (h >= 6 and h - a >= 2) or (a >= 6 and a - h >= 2)


def match_win_probability(state: MatchState, pa: float, pb: float) -> float | None:
    """P(home wins the match) from a live scoreboard state, or None when the
    state can't support a computation (unknown server, malformed points)."""
    server = state.serving
    if server not in (1, 2):
        return None

    sh = sa = 0
    cur_ga = cur_gb = 0
    for h, a in state.set_games:
        if _set_complete(h, a):
            if h > a:
                sh += 1
            else:
                sa += 1
        else:
            cur_ga, cur_gb = h, a

    if state.tiebreak:
        try:
            ta, tb = int(state.points[0]), int(state.points[1])
        except ValueError:
            ta = tb = 0
        # Recover who served point 1 from the current server and rotation.
        first = server if ((ta + tb + 1) // 2) % 2 == 0 else 3 - server
        p_set = tb_win_prob(pa, pb, ta, tb, first)
    else:
        a_pt = POINT_MAP.get(state.points[0], 0)
        b_pt = POINT_MAP.get(state.points[1], 0)
        p_srv = pa if server == 1 else pb
        srv_pts, ret_pts = (a_pt, b_pt) if server == 1 else (b_pt, a_pt)
        hold = game_win_prob(p_srv, srv_pts, ret_pts)
        p_home_game = hold if server == 1 else 1 - hold
        p_set = p_home_game * set_win_prob(pa, pb, cur_ga + 1, cur_gb, 3 - server) + (
            1 - p_home_game
        ) * set_win_prob(pa, pb, cur_ga, cur_gb + 1, 3 - server)

    return p_set * match_from_sets(pa, pb, sh + 1, sa, state.best_of) + (
        1 - p_set
    ) * match_from_sets(pa, pb, sh, sa + 1, state.best_of)


def calibrate_serve_points(
    state: MatchState, target_home_prob: float, base: float = BASE_SERVE_WIN
) -> tuple[float, float] | None:
    """Solve for (pa, pb) = (base + d, base - d) such that the model's home
    win probability at `state` equals the market's. Bakes in any market error
    at calibration time — the price of not needing external player stats."""
    target = min(max(target_home_prob, 0.02), 0.98)
    lo, hi = -MAX_SKEW, MAX_SKEW
    for _ in range(50):
        d = (lo + hi) / 2
        m = match_win_probability(state, base + d, base - d)
        if m is None:
            return None
        if m < target:
            lo = d
        else:
            hi = d
    d = round((lo + hi) / 2, 6)
    return (base + d, base - d)
