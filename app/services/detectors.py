from app.core.contract_buffer import Tick


def microprice(tick: Tick) -> float | None:
    if not tick.bid_size or not tick.ask_size:
        return None
    denom = tick.bid_size + tick.ask_size
    return (tick.bid * tick.ask_size + tick.ask * tick.bid_size) / denom


def microprice_delta(window: list[Tick], baseline_size: int = 10, recent_size: int = 5) -> float | None:
    prices = [microprice(t) for t in window]
    prices = [p for p in prices if p is not None]
    if len(prices) < baseline_size + recent_size:
        return None
    baseline = sum(prices[:baseline_size]) / baseline_size
    recent = sum(prices[-recent_size:]) / recent_size
    return recent - baseline

def volume_spike(window: list[Tick], baseline_size: int = 10, recent_size: int = 5) -> float | None:
    volumes = [tick.volume_10s for tick in window]
    if len(volumes) < baseline_size + recent_size:
        return None
    baseline = sum(volumes[:baseline_size]) / baseline_size
    recent = sum(volumes[-recent_size:]) / recent_size
    return recent - baseline


def imbalance_shift(window: list[Tick], baseline_size: int = 10, recent_size: int = 5) -> float | None:
    values = [t.imbalance for t in window]
    if len(values) < baseline_size + recent_size:
        return None
    baseline = sum(values[:baseline_size]) / baseline_size
    recent = sum(values[-recent_size:]) / recent_size
    return recent - baseline


def spread_compression(window: list[Tick], baseline_size: int = 10, recent_size: int = 5) -> float | None:
    values = [t.spread for t in window]
    if len(values) < baseline_size + recent_size:
        return None
    baseline = sum(values[:baseline_size]) / baseline_size
    recent = sum(values[-recent_size:]) / recent_size
    return recent - baseline


def liquidity_drain(window: list[Tick], baseline_size: int = 10, recent_size: int = 5) -> float | None:
    values = [t.liquidity for t in window if t.liquidity is not None]
    if len(values) < baseline_size + recent_size:
        return None
    baseline = sum(values[:baseline_size]) / baseline_size
    recent = sum(values[-recent_size:]) / recent_size
    return recent - baseline
