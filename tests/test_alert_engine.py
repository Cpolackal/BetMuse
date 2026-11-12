import asyncio

import pytest

from app.workers import alert_engine as ae


def _window(make_tick, **last5):
    return [make_tick() for _ in range(20)] + [make_tick(**last5) for _ in range(5)]


def test_no_alerts_on_flat_window(make_tick):
    assert ae.run_detectors([make_tick() for _ in range(25)]) == []


def test_volume_spike_fires_up(make_tick):
    alerts = ae.run_detectors(_window(make_tick, volume_10s=500))
    assert [(a["type"], a["direction"]) for a in alerts] == [("volume", "up")]


def test_spread_directions(make_tick):
    wide = ae.run_detectors(_window(make_tick, spread=0.1))
    assert wide[0]["direction"] == "widening"
    tight = ae.run_detectors([make_tick(spread=0.1) for _ in range(20)] + [make_tick(spread=0.02) for _ in range(5)])
    assert tight[0]["direction"] == "tightening"


def test_liquidity_drain_one_sided(make_tick):
    w = [make_tick(liquidity=100.0) for _ in range(20)] + [make_tick(liquidity=10.0) for _ in range(5)]
    assert ae.run_detectors(w)[0]["type"] == "liquidity"
    rising = [make_tick(liquidity=10.0) for _ in range(20)] + [make_tick(liquidity=100.0) for _ in range(5)]
    assert ae.run_detectors(rising) == []


def test_window_spans_pause():
    from collections import deque
    assert not ae.window_spans_pause(deque([0, 10, 20]))
    assert ae.window_spans_pause(deque([0, 10, 70]))


def test_posterior_prior_dominates_without_data(make_state):
    assert ae._posterior_serve_points(make_state(), 0.65, 0.62) == (0.65, 0.62)


def test_posterior_moves_toward_observed(make_state):
    s = make_state(serve_played=(100, 100), serve_won=(80, 40))
    pa, pb = ae._posterior_serve_points(s, 0.6, 0.6)
    assert pa == pytest.approx(0.7) and pb == pytest.approx(0.5)


class TestTracker:
    def _run(self, make_tick, make_state, mid, n):
        prices: dict = {}
        tr = ae.ModelDivergenceTracker(prices)
        state, link = make_state(), (1, 1)
        # First eligible tick calibrates to the market and never alerts.
        assert tr.evaluate(make_tick(bid=0.49, ask=0.51), link, state) is None
        out = None
        for _ in range(n):
            out = tr.evaluate(make_tick(bid=mid - 0.01, ask=mid + 0.01), link, state)
        return tr, prices, out

    def test_calibration_tick_publishes_no_price(self, make_tick, make_state):
        tr = ae.ModelDivergenceTracker({})
        tr.evaluate(make_tick(), (1, 1), make_state())
        assert 1 in tr.calibrations and tr.model_prices == {}

    def test_persistent_edge_fires_once_then_resets(self, make_tick, make_state):
        tr, prices, out = self._run(make_tick, make_state, mid=0.75, n=ae.MODEL_EDGE_PERSIST)
        assert out["type"] == "model_divergence" and out["direction"] == "rich"
        assert tr.edge_streaks["KXATPMATCH-TEST"] == 0
        assert prices["KXATPMATCH-TEST"]["edge"] > ae.MODEL_EDGE_THRESHOLD

    def test_short_streak_does_not_fire(self, make_tick, make_state):
        _, _, out = self._run(make_tick, make_state, mid=0.75, n=ae.MODEL_EDGE_PERSIST - 1)
        assert out is None

    def test_ignores_unlinked_and_not_live(self, make_tick, make_state):
        tr = ae.ModelDivergenceTracker({})
        assert tr.evaluate(make_tick(), None, make_state()) is None
        assert tr.evaluate(make_tick(), (1, 1), make_state(status="notstarted")) is None
        assert tr.calibrations == {}


class FakeRedis:
    def __init__(self, entries):
        self.entries, self.acked, self.added = entries, [], []

    async def xreadgroup(self, **_):
        if self.entries:
            e, self.entries = self.entries, []
            return [("ticks", e)]
        raise asyncio.CancelledError

    async def xack(self, _s, _g, msg_id):
        self.acked.append(msg_id)

    async def xadd(self, stream, fields, maxlen=None):
        self.added.append((stream, fields))


def test_engine_acks_everything_and_emits(make_tick):
    ticks = [make_tick(volume_10s=0 if i < 20 else 500) for i in range(25)]
    entries = [(f"{1000 + i}-0", {"ticks": t.model_dump_json()}) for i, t in enumerate(ticks)]
    entries.insert(3, ("1003-5", {"ticks": "not json"}))
    r = FakeRedis(entries)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ae.alert_engine(r))
    assert len(r.acked) == 26
    assert [f["type"] for _, f in r.added] == ["volume"]
    assert r.added[0][1]["market"] == "KXATPMATCH-TEST" and "_log" not in r.added[0][1]
