from itertools import islice
import time
from collections import deque
from pydantic import BaseModel

class Tick(BaseModel):
    market: str
    price: float
    bid: float
    ask: float
    spread: float
    volume_1s: int
    volume_10s: int
    volume_60s: int
    imbalance: float
    momentum: float
    last_trade_ts: int
    no_bid: float | None = None
    no_ask: float | None = None
    liquidity: float | None = None
    open_interest: float | None = None
    dollar_volume: int | None = None
    dollar_open_interest: int | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last_trade_size: float | None = None




class contract_buffer():

    def __init__(self, maxlen=600):
        self.items = deque(maxlen=600)
        self.last_seen: float = time.monotonic()

    def push(self, tick: Tick):
        self.items.append(tick)
        self.last_seen = time.monotonic()
    
    def latest(self):
        return self.items[-1] if self.items else None

    def len(self):
        return len(self.items)

    def tail(self, count: int) -> list:
        start = max(0, self.len() - count)
        return list(islice(self.items, start, self.len()))