"""
Market analytics service for Kalshi ticker_v2 messages.

Given per-tick data, compute per-market fields:
- price, bid, ask, spread
- volume_1s, volume_10s, volume_60s
- momentum
- imbalance
- last_trade_ts
"""
import time
from collections import deque
from typing import Deque, Dict, Tuple, Any


# In-memory sliding history per market to compute volumes & momentum
# markets_history[ticker] = deque[(ts, price, cum_volume)]
markets_history: Dict[str, Deque[Tuple[float, float, float]]] = {}


def compute_market_analytics(ticker: str, msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given a raw ticker_v2 message, compute analytics for a single market:
    price, bid, ask, spread, volume_1s, volume_10s, volume_60s, momentum,
    imbalance, last_trade_ts.
    """
    # Kalshi ticker_v2 typically includes price (cents), yes_bid, yes_ask, volume, ts, etc.
    # Fallbacks keep things robust if some fields are missing.
    ts = msg.get("ts")
    if ts is None:
        ts = time.time()
    else:
        # Assume ts is seconds since epoch; if it's something else, this still increases monotonically.
        ts = float(ts)

    price_raw = msg.get("price")
    price: float = float(price_raw) / 100.0 if isinstance(price_raw, (int, float)) else float("nan")

    bid_raw = msg.get("yes_bid")
    ask_raw = msg.get("yes_ask")
    bid = float(bid_raw) / 100.0 if isinstance(bid_raw, (int, float)) else float("nan")
    ask = float(ask_raw) / 100.0 if isinstance(ask_raw, (int, float)) else float("nan")

    spread = ask - bid if not any(map(lambda v: v != v, (bid, ask))) else float("nan")  # NaN check via v!=v

    # Use cumulative volume if available; otherwise treat as 0
    cum_vol_raw = msg.get("volume")
    cum_vol = float(cum_vol_raw) if isinstance(cum_vol_raw, (int, float)) else 0.0

    history = markets_history.setdefault(ticker, deque())
    history.append((ts, price, cum_vol))

    # Keep only last 60 seconds of history
    cutoff = ts - 60.0
    while history and history[0][0] < cutoff:
        history.popleft()

    def volume_over(seconds: float) -> float:
        if not history:
            return 0.0
        window_start = ts - seconds
        # Find earliest sample within window; fall back to oldest
        base_vol = history[0][2]
        for h_ts, _h_price, h_vol in history:
            if h_ts >= window_start:
                base_vol = h_vol
                break
        return max(0.0, cum_vol - base_vol)

    vol_1s = volume_over(1.0)
    vol_10s = volume_over(10.0)
    vol_60s = volume_over(60.0)

    # Momentum: price change over the last 60 seconds (if we have an older sample)
    momentum = 0.0
    for h_ts, h_price, _h_vol in history:
        if h_ts >= cutoff:
            # first sample within 60s window
            if h_price == h_price and price == price:  # both not NaN
                momentum = price - h_price
            break

    # Simple imbalance metric based on bid/ask symmetry:
    # (bid - ask) / (bid + ask); if invalid, set to 0.0
    if bid == bid and ask == ask and (bid + ask) > 0:
        imbalance = (bid - ask) / (bid + ask)
    else:
        imbalance = 0.0

    return {
        "price": price,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "volume_1s": int(vol_1s),
        "volume_10s": int(vol_10s),
        "volume_60s": int(vol_60s),
        "momentum": momentum,
        "imbalance": imbalance,
        "last_trade_ts": int(ts),
    }

