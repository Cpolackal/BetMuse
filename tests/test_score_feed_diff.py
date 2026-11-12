import pytest

from app.workers.score_feed import _diff_game_point, _diff_point, _merge_serve_stats


@pytest.mark.parametrize("old,new,expected", [
    (("0", "0"), ("15", "0"), 1),
    (("0", "0"), ("0", "15"), 2),
    (("30", "40"), ("30", "0"), None),
    (("40", "40"), ("A", "40"), 1),
    (("40", "40"), ("40", "A"), 2),
    (("A", "40"), ("40", "40"), 2),   # advantage lost -> other player won point
    (("40", "A"), ("40", "40"), 1),
    (("15", "0"), ("40", "0"), None),  # skipped a point
])
def test_diff_game_point(old, new, expected):
    assert _diff_game_point(old, new) == expected


def test_diff_point_ignores_tiebreak_and_server_change(make_state):
    a = make_state(points=("0", "0"))
    assert _diff_point(a, make_state(points=("15", "0"))) == 1
    assert _diff_point(a, make_state(points=("15", "0"), tiebreak=True)) is None
    assert _diff_point(a, make_state(points=("15", "0"), serving=2)) is None
    assert _diff_point(a, make_state(points=("15", "0"), set_games=[(0, 1)])) is None


def test_merge_credits_server(make_state):
    prev = make_state(points=("0", "0"), serving=1)
    out = _merge_serve_stats(prev, make_state(points=("15", "0")))
    assert out.serve_played == (1, 0) and out.serve_won == (1, 0)
    out2 = _merge_serve_stats(out, make_state(points=("15", "15")))
    assert out2.serve_played == (2, 0) and out2.serve_won == (1, 0)


def test_merge_without_prev_passes_through(make_state):
    s = make_state()
    assert _merge_serve_stats(None, s) is s
