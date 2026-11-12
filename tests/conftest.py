import os

os.environ.setdefault("DATABASE_URL", "sqlite://")  # engine is lazy; tests never touch the DB

import pytest

from app.core.contract_buffer import Tick
from app.core.match_state import MatchState


@pytest.fixture
def make_tick():
    def _make(**kw) -> Tick:
        base = dict(
            market="KXATPMATCH-TEST", price=0.5, bid=0.49, ask=0.51, spread=0.02,
            volume_1s=0, volume_10s=0, volume_60s=0, imbalance=0.0, momentum=0.0,
            last_trade_ts=0,
        )
        base.update(kw)
        return Tick(**base)
    return _make


@pytest.fixture
def make_state():
    def _make(**kw) -> MatchState:
        base = dict(
            event_id=1, home="A", away="B", tournament="T", category="ATP",
            status="inprogress", set_games=[(0, 0)], points=("0", "0"), serving=1,
        )
        base.update(kw)
        return MatchState(**base)
    return _make
