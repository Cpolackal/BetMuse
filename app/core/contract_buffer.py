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




class contract_buffer():

    def __init__(self, maxlen=600):
        self.items = deque(maxlen=600)

    def push(self, tick: Tick):
        self.items.append(tick)
    
    def latest(self):
        return self.items[-1] if self.ticks else None
    
    def len(self):
        return len(self.items)


