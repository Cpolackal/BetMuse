import pytest

from app.services import detectors


def _window(make_tick, field, baseline, recent, n_base=10, n_recent=5, fill=0):
    """25-tick window: first 10 at `baseline`, last 5 at `recent`, rest `fill`."""
    vals = [baseline] * n_base + [fill] * (25 - n_base - n_recent) + [recent] * n_recent
    return [make_tick(**{field: v}) for v in vals]


@pytest.mark.parametrize("fn,field", [
    (detectors.volume_spike, "volume_10s"),
    (detectors.imbalance_shift, "imbalance"),
    (detectors.spread_compression, "spread"),
])
def test_delta_is_recent_minus_baseline(make_tick, fn, field):
    w = _window(make_tick, field, baseline=1, recent=4, fill=1)
    assert fn(w) == pytest.approx(3)


@pytest.mark.parametrize("fn", [
    detectors.microprice_delta, detectors.volume_spike, detectors.imbalance_shift,
    detectors.spread_compression, detectors.liquidity_drain,
])
def test_short_window_returns_none(make_tick, fn):
    assert fn([make_tick(bid_size=1, ask_size=1, liquidity=1.0) for _ in range(14)]) is None


def test_microprice_weights_toward_thin_side(make_tick):
    # More size on the bid -> price pulled toward the ask.
    t = make_tick(bid=0.40, ask=0.50, bid_size=90, ask_size=10)
    assert detectors.microprice(t) == pytest.approx((0.40 * 10 + 0.50 * 90) / 100)


def test_microprice_none_without_sizes(make_tick):
    assert detectors.microprice(make_tick()) is None


def test_liquidity_drain_skips_missing_values(make_tick):
    w = [make_tick(liquidity=None) for _ in range(10)]
    w += [make_tick(liquidity=10.0) for _ in range(10)] + [make_tick(liquidity=2.0) for _ in range(5)]
    assert detectors.liquidity_drain(w) == pytest.approx(2.0 - 10.0)
