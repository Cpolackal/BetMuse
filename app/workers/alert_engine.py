import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

from pydantic import ValidationError

from app.core.contract_buffer import Tick
from app.core.match_state import MatchState
from app.services.detectors import (
    imbalance_shift,
    liquidity_drain,
    microprice_delta,
    spread_compression,
    volume_spike,
)
from app.services.tennis_model import calibrate_serve_points, match_win_probability

logger = logging.getLogger(__name__)

MIN_TICKS = 25
DELTA_THRESHOLD = 0.02
VOL_THRESHOLD = 100
IMBALANCE_THRESHOLD = 0.1
SPREAD_THRESHOLD = 0.01
LIQUIDITY_THRESHOLD = -5.0
COOLDOWN_SECONDS = 30
ALERTS_MAXLEN = 10000
# Ticks only arrive on book activity, so a tennis changeover (~90s) or set
# break (~120s) shows up as a gap in arrival times. Normal between-point gaps
# run up to ~25s; 45s separates scheduled pauses from live play.
PAUSE_GAP_SECONDS = 45.0
# Model divergence must clear this edge for this many consecutive ticks.
MODEL_EDGE_THRESHOLD = 0.04
MODEL_EDGE_PERSIST = 5
# Beta-Binomial pseudo-count: how many "virtual" points the calibrated prior
# is worth against real in-play serve points. At 0 real points the model
# uses the prior outright; by ~1-2 games of serve data it's mostly observed.
SERVE_PRIOR_WEIGHT = 100


@dataclass(frozen=True)
class DetectorSpec:
    """One microstructure detector: fires when `trigger(value)` holds, and
    `direction(value)` names the side for the alert payload."""

    alert_type: str
    label: str
    fn: Callable[[list[Tick]], float | None]
    trigger: Callable[[float], bool]
    direction: Callable[[float], str]


DETECTORS: tuple[DetectorSpec, ...] = (
    DetectorSpec("microprice", "microprice", microprice_delta,
                 lambda v: abs(v) >= DELTA_THRESHOLD, lambda v: "up" if v > 0 else "down"),
    DetectorSpec("volume", "volume spike", volume_spike,
                 lambda v: abs(v) >= VOL_THRESHOLD, lambda v: "up" if v > 0 else "down"),
    DetectorSpec("imbalance", "imbalance shift", imbalance_shift,
                 lambda v: abs(v) >= IMBALANCE_THRESHOLD, lambda v: "buy" if v > 0 else "sell"),
    DetectorSpec("spread", "spread", spread_compression,
                 lambda v: abs(v) >= SPREAD_THRESHOLD, lambda v: "tightening" if v < 0 else "widening"),
    DetectorSpec("liquidity", "liquidity drain", liquidity_drain,
                 lambda v: v <= LIQUIDITY_THRESHOLD, lambda _v: "drain"),
)


def window_spans_pause(arrivals: deque) -> bool:
    return any(b - a > PAUSE_GAP_SECONDS for a, b in pairwise(arrivals))


def _mid_price(tick: Tick) -> float | None:
    if tick.bid > 0 and tick.ask > 0:
        return (tick.bid + tick.ask) / 2
    return tick.price if tick.price > 0 else None


def _posterior_serve_points(state: MatchState, pa_cal: float, pb_cal: float) -> tuple[float, float]:
    """Blend the once-per-match calibrated prior with this match's own
    in-play serve points (Beta-Binomial posterior mean)."""
    won_h, won_a = state.serve_won
    played_h, played_a = state.serve_played
    pa = (SERVE_PRIOR_WEIGHT * pa_cal + won_h) / (SERVE_PRIOR_WEIGHT + played_h)
    pb = (SERVE_PRIOR_WEIGHT * pb_cal + won_a) / (SERVE_PRIOR_WEIGHT + played_a)
    return pa, pb


def run_detectors(window: list[Tick]) -> list[dict]:
    """Evaluate every detector on `window`; return one alert dict per trigger."""
    alerts = []
    for spec in DETECTORS:
        value = spec.fn(window)
        if value is not None and spec.trigger(value):
            alerts.append({
                "type": spec.alert_type,
                "direction": spec.direction(value),
                "value": str(value),
                "_log": f"{spec.label} {spec.direction(value)} {value:+.4f}",
            })
    return alerts


class ModelDivergenceTracker:
    """Per-process model state: one serve-skew calibration per match and a
    consecutive-ticks-over-threshold streak per market."""

    def __init__(self, model_prices: dict | None = None):
        self.model_prices = model_prices
        self.calibrations: dict[int, tuple[float, float]] = {}
        self.edge_streaks: dict[str, int] = {}

    def evaluate(self, tick: Tick, link: tuple[int, int] | None, state: MatchState | None) -> dict | None:
        """Update the model price for `tick.market`; return an alert dict when
        the edge has persisted long enough, else None."""
        if link is None or state is None:
            return None
        if state.status != "inprogress" or state.serving not in (1, 2):
            return None
        event_id, side = link
        mid = _mid_price(tick)
        if mid is None or not 0.02 < mid < 0.98:
            return None

        params = self.calibrations.get(event_id)
        if params is None:
            params = calibrate_serve_points(state, mid if side == 1 else 1 - mid)
            if params:
                self.calibrations[event_id] = params
                logger.info("calibrated %s pa=%.3f pb=%.3f at %.2f", tick.market, params[0], params[1], mid)
            return None

        pa, pb = _posterior_serve_points(state, *params)
        p_home = match_win_probability(state, pa, pb)
        if p_home is None:
            return None
        model_p = p_home if side == 1 else 1 - p_home
        edge = mid - model_p
        if self.model_prices is not None:
            self.model_prices[tick.market] = {
                "model_price": model_p, "market_price": mid, "edge": edge,
                "pa": pa, "pb": pb, "ts": time.time(),
            }

        streak = self.edge_streaks.get(tick.market, 0) + 1 if abs(edge) >= MODEL_EDGE_THRESHOLD else 0
        if streak < MODEL_EDGE_PERSIST:
            self.edge_streaks[tick.market] = streak
            return None
        self.edge_streaks[tick.market] = 0
        direction = "rich" if edge > 0 else "cheap"
        return {
            "type": "model_divergence", "direction": direction, "value": str(edge),
            "model_price": str(round(model_p, 4)), "market_price": str(round(mid, 4)),
            "_log": f"model divergence {direction} edge={edge:+.3f} (market {mid:.2f} vs model {model_p:.2f})",
        }


async def _emit(redis_client, market: str, alert: dict) -> None:
    fields = {k: v for k, v in alert.items() if k != "_log"}
    fields.update(market=market, ts=str(time.time()))
    logger.info("[ALERT] %s %s", market, alert["_log"])
    await redis_client.xadd("alerts", fields, maxlen=ALERTS_MAXLEN)


async def alert_engine(redis_client, match_states=None, market_links=None, model_prices=None):
    last_alerted: dict[str, float] = {}
    windows: dict[str, deque] = {}
    arrivals: dict[str, deque] = {}
    tracker = ModelDivergenceTracker(model_prices)

    while True:
        result = await redis_client.xreadgroup(
            groupname="alert_engine",
            consumername="alt-1",
            streams={"ticks": ">"},
            count=100,
            block=5000,
        )
        if not result:
            continue
        _, entries = result[0]
        for msg_id, fields in entries:
            try:
                tick = Tick.model_validate_json(fields["ticks"])
            except ValidationError:
                logger.warning("dropping invalid tick %s", msg_id, exc_info=True)
                await redis_client.xack("ticks", "alert_engine", msg_id)
                continue
            try:
                window = windows.setdefault(tick.market, deque(maxlen=MIN_TICKS))
                window.append(tick)
                # Stream IDs are "<unix_ms>-<seq>": the time the tick hit the
                # stream, which stays correct even when replaying a backlog.
                arrival_times = arrivals.setdefault(tick.market, deque(maxlen=MIN_TICKS))
                arrival_times.append(float(str(msg_id).split("-")[0]) / 1000.0)

                if len(window) < MIN_TICKS:
                    continue
                # Baseline-vs-recent comparisons are meaningless across a
                # changeover; skip until the window refills with live-play ticks.
                if window_spans_pause(arrival_times):
                    continue
                now = time.monotonic()
                if now - last_alerted.get(tick.market, 0) < COOLDOWN_SECONDS:
                    continue

                alerts = run_detectors(list(window))
                if match_states is not None and market_links is not None:
                    link = market_links.get(tick.market)
                    state = match_states.get(link[0]) if link else None
                    divergence = tracker.evaluate(tick, link, state)
                    if divergence:
                        alerts.append(divergence)

                for alert in alerts:
                    await _emit(redis_client, tick.market, alert)
                if alerts:
                    last_alerted[tick.market] = now
            finally:
                await redis_client.xack("ticks", "alert_engine", msg_id)
