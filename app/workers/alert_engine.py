import time
from collections import deque
from itertools import pairwise
from app.core.contract_buffer import Tick
from pydantic import ValidationError
from app.services.detectors import (
    microprice_delta,
    volume_spike,
    imbalance_shift,
    spread_compression,
    liquidity_drain,
)
from app.services.tennis_model import calibrate_serve_points, match_win_probability

MIN_TICKS = 25
DELTA_THRESHOLD = 0.02
VOL_THRESHOLD = 100
IMBALANCE_THRESHOLD = 0.1
SPREAD_THRESHOLD = 0.01
LIQUIDITY_THRESHOLD = -5.0
COOLDOWN_SECONDS = 30
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


def window_spans_pause(arrivals: deque) -> bool:
    return any(b - a > PAUSE_GAP_SECONDS for a, b in pairwise(arrivals))


def _mid_price(tick: Tick) -> float | None:
    if tick.bid > 0 and tick.ask > 0:
        return (tick.bid + tick.ask) / 2
    return tick.price if tick.price > 0 else None


def _posterior_serve_points(state, pa_cal: float, pb_cal: float) -> tuple[float, float]:
    """Blend the once-per-match calibrated prior with this match's own
    in-play serve points (Beta-Binomial posterior mean)."""
    won_h, won_a = state.serve_won
    played_h, played_a = state.serve_played
    pa = (SERVE_PRIOR_WEIGHT * pa_cal + won_h) / (SERVE_PRIOR_WEIGHT + played_h)
    pb = (SERVE_PRIOR_WEIGHT * pb_cal + won_a) / (SERVE_PRIOR_WEIGHT + played_a)
    return pa, pb


async def alert_engine(redis_client, match_states=None, market_links=None, model_prices=None):
    last_alerted: dict[str, float] = {}
    windows: dict[str, deque] = {}
    arrivals: dict[str, deque] = {}
    calibrations: dict[int, tuple[float, float]] = {}
    edge_streaks: dict[str, int] = {}

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
                ticked = Tick.model_validate_json(fields["ticks"])

                window = windows.setdefault(ticked.market, deque(maxlen=MIN_TICKS))
                window.append(ticked)
                # Stream IDs are "<unix_ms>-<seq>": the time the tick hit the
                # stream, which stays correct even when replaying a backlog.
                arrival_times = arrivals.setdefault(ticked.market, deque(maxlen=MIN_TICKS))
                arrival_times.append(float(str(msg_id).split("-")[0]) / 1000.0)

                if len(window) < MIN_TICKS:
                    await redis_client.xack("ticks", "alert_engine", msg_id)
                    continue

                # Baseline-vs-recent comparisons are meaningless across a
                # changeover; skip until the window refills with live-play ticks.
                if window_spans_pause(arrival_times):
                    await redis_client.xack("ticks", "alert_engine", msg_id)
                    continue

                now = time.monotonic()
                if now - last_alerted.get(ticked.market, 0) < COOLDOWN_SECONDS:
                    await redis_client.xack("ticks", "alert_engine", msg_id)
                    continue

                window_list = list(window)
                fired = False

                delta = microprice_delta(window_list)
                if delta is not None and abs(delta) >= DELTA_THRESHOLD:
                    direction = "up" if delta > 0 else "down"
                    print(f"[ALERT] {ticked.market} microprice {direction} {delta:+.4f}")
                    await redis_client.xadd("alerts", {
                        "market": ticked.market, "type": "microprice",
                        "direction": direction, "value": str(delta), "ts": str(time.time()),
                    }, maxlen=10000)
                    fired = True

                vol_diff = volume_spike(window_list)
                if vol_diff is not None and abs(vol_diff) >= VOL_THRESHOLD:
                    direction = "up" if vol_diff > 0 else "down"
                    print(f"[ALERT] {ticked.market} volume spike {direction} {vol_diff:+.4f}")
                    await redis_client.xadd("alerts", {
                        "market": ticked.market, "type": "volume",
                        "direction": direction, "value": str(vol_diff), "ts": str(time.time()),
                    }, maxlen=10000)
                    fired = True

                imbalance = imbalance_shift(window_list)
                if imbalance is not None and abs(imbalance) >= IMBALANCE_THRESHOLD:
                    direction = "buy" if imbalance > 0 else "sell"
                    print(f"[ALERT] {ticked.market} imbalance shift {direction} {imbalance:+.4f}")
                    await redis_client.xadd("alerts", {
                        "market": ticked.market, "type": "imbalance",
                        "direction": direction, "value": str(imbalance), "ts": str(time.time()),
                    }, maxlen=10000)
                    fired = True

                compression = spread_compression(window_list)
                if compression is not None and abs(compression) >= SPREAD_THRESHOLD:
                    direction = "tightening" if compression < 0 else "widening"
                    print(f"[ALERT] {ticked.market} spread {direction} {compression:+.4f}")
                    await redis_client.xadd("alerts", {
                        "market": ticked.market, "type": "spread",
                        "direction": direction, "value": str(compression), "ts": str(time.time()),
                    }, maxlen=10000)
                    fired = True

                drain = liquidity_drain(window_list)
                if drain is not None and drain <= LIQUIDITY_THRESHOLD:
                    print(f"[ALERT] {ticked.market} liquidity drain {drain:+.4f}")
                    await redis_client.xadd("alerts", {
                        "market": ticked.market, "type": "liquidity",
                        "direction": "drain", "value": str(drain), "ts": str(time.time()),
                    }, maxlen = 10000)
                    fired = True

                if match_states is not None and market_links is not None:
                    link = market_links.get(ticked.market)
                    state = match_states.get(link[0]) if link else None
                    if state is not None and state.status == "inprogress" and state.serving in (1, 2):
                        event_id, side = link
                        mid = _mid_price(ticked)
                        if mid is not None and 0.02 < mid < 0.98:
                            home_target = mid if side == 1 else 1 - mid
                            params = calibrations.get(event_id)
                            if params is None:
                                params = calibrate_serve_points(state, home_target)
                                if params:
                                    calibrations[event_id] = params
                                    print(f"[ALERT-ENGINE] calibrated {ticked.market} pa={params[0]:.3f} pb={params[1]:.3f} at {mid:.2f}")
                            else:
                                pa_live, pb_live = _posterior_serve_points(state, *params)
                                p_home = match_win_probability(state, pa_live, pb_live)
                                if p_home is not None:
                                    model_p = p_home if side == 1 else 1 - p_home
                                    edge = mid - model_p
                                    if model_prices is not None:
                                        model_prices[ticked.market] = {
                                            "model_price": model_p, "market_price": mid,
                                            "edge": edge, "pa": pa_live, "pb": pb_live,
                                            "ts": time.time(),
                                        }
                                    if abs(edge) >= MODEL_EDGE_THRESHOLD:
                                        edge_streaks[ticked.market] = edge_streaks.get(ticked.market, 0) + 1
                                    else:
                                        edge_streaks[ticked.market] = 0
                                    if edge_streaks[ticked.market] >= MODEL_EDGE_PERSIST:
                                        direction = "rich" if edge > 0 else "cheap"
                                        print(f"[ALERT] {ticked.market} model divergence {direction} edge={edge:+.3f} (market {mid:.2f} vs model {model_p:.2f})")
                                        await redis_client.xadd("alerts", {
                                            "market": ticked.market, "type": "model_divergence",
                                            "direction": direction, "value": str(edge), "ts": str(time.time()),
                                            "model_price": str(round(model_p, 4)), "market_price": str(round(mid, 4)),
                                        }, maxlen=10000)
                                        edge_streaks[ticked.market] = 0
                                        fired = True

                if fired:
                    last_alerted[ticked.market] = now

            except ValidationError:
                pass
            await redis_client.xack("ticks", "alert_engine", msg_id)
