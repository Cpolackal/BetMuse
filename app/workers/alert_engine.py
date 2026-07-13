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


def window_spans_pause(arrivals: deque) -> bool:
    return any(b - a > PAUSE_GAP_SECONDS for a, b in pairwise(arrivals))


async def alert_engine(redis_client):
    last_alerted: dict[str, float] = {}
    windows: dict[str, deque] = {}
    arrivals: dict[str, deque] = {}

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

                if fired:
                    last_alerted[ticked.market] = now

            except ValidationError:
                pass
            await redis_client.xack("ticks", "alert_engine", msg_id)
