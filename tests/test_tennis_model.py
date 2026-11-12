import pytest

from app.services.tennis_model import (
    calibrate_serve_points,
    game_win_prob,
    match_win_probability,
    set_win_prob,
)


def test_game_win_prob_boundaries():
    assert game_win_prob(0.5) == pytest.approx(0.5)
    assert game_win_prob(0.0) == 0.0
    assert game_win_prob(1.0) == 1.0


def test_game_win_prob_known_value():
    # Standard result: p=0.6 -> ~0.7357
    assert game_win_prob(0.6) == pytest.approx(0.7357, abs=1e-3)


def test_game_win_prob_from_score_is_monotone():
    assert game_win_prob(0.6, 3, 0) > game_win_prob(0.6, 1, 0) > game_win_prob(0.6, 0, 3)


def test_symmetric_players_start_even(make_state):
    s = make_state(set_games=[(0, 0)])
    assert match_win_probability(s, 0.65, 0.65) == pytest.approx(0.5, abs=0.02)


def test_leading_player_favoured(make_state):
    s = make_state(set_games=[(6, 2), (3, 1)])
    assert match_win_probability(s, 0.65, 0.65) > 0.9


def test_unknown_server_returns_none(make_state):
    assert match_win_probability(make_state(serving=None), 0.65, 0.65) is None


def test_stronger_server_raises_home_prob(make_state):
    s = make_state()
    assert match_win_probability(s, 0.70, 0.65) > match_win_probability(s, 0.65, 0.65)


def test_calibration_roundtrip(make_state):
    s = make_state(set_games=[(2, 1)])
    pa, pb = calibrate_serve_points(s, 0.7)
    assert match_win_probability(s, pa, pb) == pytest.approx(0.7, abs=0.01)


def test_calibration_clamps_extreme_target(make_state):
    assert calibrate_serve_points(make_state(), 1.5) is not None


def test_set_win_prob_in_unit_interval():
    assert 0 < set_win_prob(0.65, 0.65, 0, 0, 1) < 1
