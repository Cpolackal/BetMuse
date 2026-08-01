"""Backtest the model_divergence detector's threshold/persistence policy
against stored market_snapshots.

For each (threshold, persist_ticks) combination this replays the same streak
logic as app/workers/alert_engine.py's MODEL_EDGE_THRESHOLD /
MODEL_EDGE_PERSIST offline against historical `edge = mid - model_price`
series, then checks whether the edge actually shrank 1/5/15 minutes after
each simulated signal. It only evaluates the divergence detector in
isolation (no cooldown coupling with the other detectors, no pause-gate) —
the point is to answer "does this threshold/persistence pair predict
convergence at all", which decides whether MODEL_EDGE_THRESHOLD=0.04 /
MODEL_EDGE_PERSIST=5 in alert_engine.py should change.

Usage:
    DATABASE_URL=... python scripts/backtest_divergence.py
    DATABASE_URL=... python scripts/backtest_divergence.py --ticker-prefix KXATPMATCH --min-signals 5
"""
import argparse
import bisect
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

# Allow running as `python scripts/backtest_divergence.py` from the repo root
# without needing PYTHONPATH set.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.db.session import SessionLocal

THRESHOLDS = [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]
PERSISTENCE = [3, 4, 5, 6, 7, 8, 9, 10]
HORIZONS_MIN = [1, 5, 15]
# db_writer snapshots every 5s; a gap wider than this means no snapshot
# actually landed near the target horizon (match paused, market delisted).
NEAREST_TOLERANCE = timedelta(seconds=90)


@dataclass
class Point:
    ts: datetime
    edge: float


def load_series(db, ticker_prefix: str) -> dict[str, list[Point]]:
    rows = db.execute(text("""
        select ticker, snapshot_time, last_price, yes_bid, yes_ask, model_price
        from market_snapshots
        where model_price is not null and ticker like :prefix
        order by ticker, snapshot_time
    """), {"prefix": f"{ticker_prefix}%"}).fetchall()

    series: dict[str, list[Point]] = defaultdict(list)
    for ticker, ts, last_price, bid, ask, model_price in rows:
        mid = (bid + ask) / 2 if bid is not None and ask is not None else last_price
        if mid is None:
            continue
        series[ticker].append(Point(ts=ts, edge=mid - model_price))
    return series


def nearest_edge(points: list[Point], ts_list: list[datetime], target_ts: datetime) -> float | None:
    i = bisect.bisect_left(ts_list, target_ts)
    candidates = [j for j in (i - 1, i) if 0 <= j < len(points)]
    if not candidates:
        return None
    best = min(candidates, key=lambda j: abs(ts_list[j] - target_ts))
    if abs(ts_list[best] - target_ts) > NEAREST_TOLERANCE:
        return None
    return points[best].edge


def simulate(series: dict[str, list[Point]], threshold: float, persist: int) -> list[dict]:
    """Mirrors alert_engine's edge_streaks logic: streak resets on any tick
    below threshold, and resets to 0 immediately after a signal fires (so a
    sustained divergence produces one signal, not one per tick)."""
    signals = []
    for ticker, points in series.items():
        streak = 0
        for p in points:
            if abs(p.edge) >= threshold:
                streak += 1
            else:
                streak = 0
                continue
            if streak >= persist:
                signals.append((ticker, p))
                streak = 0

    results = []
    for ticker, p in signals:
        points = series[ticker]
        ts_list = [pt.ts for pt in points]
        row = {"ticker": ticker, "ts": p.ts, "edge0": p.edge}
        for h in HORIZONS_MIN:
            row[f"edge_{h}m"] = nearest_edge(points, ts_list, p.ts + timedelta(minutes=h))
        results.append(row)
    return results


def summarize(results: list[dict], threshold: float, persist: int) -> dict:
    out = {"threshold": threshold, "persist": persist, "signals": len(results)}
    for h in HORIZONS_MIN:
        decays, hits, counted = [], 0, 0
        for r in results:
            fut = r.get(f"edge_{h}m")
            if fut is None:
                continue
            counted += 1
            e0 = abs(r["edge0"])
            if e0 <= 0:
                continue
            decays.append((e0 - abs(fut)) / e0)
            if abs(fut) < e0:
                hits += 1
        out[f"n_{h}m"] = counted
        out[f"hit_rate_{h}m"] = hits / counted if counted else None
        out[f"mean_decay_{h}m"] = sum(decays) / len(decays) if decays else None
    return out


def fmt_pct(x) -> str:
    return f"{x:.0%}" if isinstance(x, float) else "  -  "


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker-prefix", default="KXATPMATCH", help="restrict to this ticker prefix")
    parser.add_argument("--min-signals", type=int, default=1, help="hide rows with fewer signals than this")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        series = load_series(db, args.ticker_prefix)
    finally:
        db.close()

    total_rows = sum(len(v) for v in series.values())
    print(f"loaded {len(series)} mapped ticker(s), {total_rows} snapshot row(s) with model_price")
    if total_rows == 0:
        print("no model_price data yet — run the pipeline (KALSHI_WS_RUN=1) during a live ATP window first.")
        return

    rows = [
        summarize(simulate(series, threshold, persist), threshold, persist)
        for threshold in THRESHOLDS
        for persist in PERSISTENCE
    ]
    rows = [r for r in rows if r["signals"] >= args.min_signals]
    if not rows:
        print(f"no (threshold, persist) combo produced >= {args.min_signals} signal(s) on this data.")
        return

    header = f"{'thr':>5} {'pers':>4} {'sig':>5} {'hit@1m':>7} {'hit@5m':>7} {'hit@15m':>8} {'decay@5m':>9}"
    print()
    print(header)
    print("-" * len(header))
    for r in sorted(rows, key=lambda r: (-r["signals"], r["threshold"], r["persist"])):
        print(
            f"{r['threshold']:>5.2f} {r['persist']:>4d} {r['signals']:>5d} "
            f"{fmt_pct(r['hit_rate_1m']):>7} {fmt_pct(r['hit_rate_5m']):>7} "
            f"{fmt_pct(r['hit_rate_15m']):>8} {fmt_pct(r['mean_decay_5m']):>9}"
        )
    print()
    print("hit@Nm = fraction of signals where |edge| shrank N minutes later.")
    print("decay@5m = mean fractional reduction in |edge| after 5 minutes (negative = edge widened).")


if __name__ == "__main__":
    main()
