"""Characterization tests for app/db/crud.py against a real Postgres."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db import crud
from app.db.models.market import market_links, market_meta, market_snapshots, match_events

NOW = datetime.now(UTC)


def day_ticker(offset_days: int, suffix: str = "AAABBB-AAA") -> str:
    d = datetime.now(UTC) + timedelta(days=offset_days)
    return f"KXATPMATCH-{d:%y}{d:%b}{d:%d}".upper() + suffix


def add_meta(db, ticker, *, event="EV", result=None, open_time=None, close_time=None, title="Will A B win?"):
    db.add(market_meta(ticker=ticker, event_ticker=event, series_ticker=event and event.split("-")[0],
                       title=title, result=result, open_time=open_time, close_time=close_time))
    db.commit()


# ---- set_market / resolve_market / get_market ----

@pytest.mark.parametrize("raw,expected", [
    (None, None), ("", None), (True, True), (False, False),
    ("yes", True), ("YES", True), ("true", True), ("1", True),
    ("no", False), ("False", False), ("0", False),
    ("maybe", None), (5, None),
])
def test_set_market_normalises_result(db, raw, expected):
    crud.set_market(db, {"ticker": "T1", "event_ticker": "KXATP-26JAN01-X", "result": raw})
    row = crud.get_market(db, "T1")
    assert row.result is expected and row.series_ticker == "KXATP"


def test_set_market_is_idempotent_and_ignores_missing_ticker(db):
    crud.set_market(db, {"ticker": "T1", "title": "first"})
    crud.set_market(db, {"ticker": "T1", "title": "second"})
    crud.set_market(db, {"title": "no ticker"})
    assert db.query(market_meta).count() == 1
    assert crud.get_market(db, "T1").title == "first"
    assert crud.get_market(db, "T1").series_ticker is None


def test_resolve_market(db):
    add_meta(db, "T1")
    assert crud.resolve_market(db, "T1", True) is True
    assert crud.get_market(db, "T1").result is True
    assert crud.resolve_market(db, "nope", True) is False


# ---- market selection ----

def test_kalshi_iso_strings_compare_correctly_whatever_the_session_timezone(db):
    """Kalshi sends open_time as an ISO string ending in Z, which set_market
    stores as-is. With naive columns Postgres drops the offset on the cast, so
    the value landed as UTC wall time and was then compared against a cutoff
    converted to the session timezone (this test server runs in New York).
    With timestamptz the offset is honoured and the result is the same
    everywhere."""
    stamp = lambda hours: (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    crud.set_market(db, {"ticker": "old", "open_time": stamp(4)})
    crud.set_market(db, {"ticker": "recent", "open_time": stamp(1)})
    assert [m.ticker for m in crud.get_unresolved_markets(db)] == ["old"]


def test_get_unresolved_markets_gates_on_open_time(db):
    add_meta(db, "old", open_time=NOW - timedelta(hours=4))
    add_meta(db, "recent", open_time=NOW - timedelta(hours=1))
    add_meta(db, "no-open", open_time=None)
    add_meta(db, "done", open_time=NOW - timedelta(hours=9), result=True)
    assert [m.ticker for m in crud.get_unresolved_markets(db)] == ["old"]


def test_get_upcoming_markets_filters_and_orders_by_ticker_date(db):
    add_meta(db, day_ticker(2), event="E-future")
    add_meta(db, day_ticker(0), event="E-today")
    add_meta(db, day_ticker(-1), event="E-yesterday")
    add_meta(db, day_ticker(-3), event="E-stale")
    add_meta(db, "NO-DATE-HERE", event="E-undated")
    add_meta(db, day_ticker(0, "CCCDDD-CCC"), event="E-resolved", result=True)
    add_meta(db, day_ticker(0, "EEEFFF-EEE"), event=None)
    got = [m.event_ticker for m in crud.get_upcoming_markets(db)]
    assert got == ["E-yesterday", "E-today", "E-future"]
    assert len(crud.get_upcoming_markets(db, limit=2)) == 2


def test_get_completed_markets_newest_first(db):
    add_meta(db, day_ticker(-2), event="E-old", result=True)
    add_meta(db, day_ticker(-1), event="E-new", result=False)
    add_meta(db, day_ticker(0, "CCCDDD-CCC"), event="E-open")  # unresolved: excluded
    add_meta(db, "NO-DATE", event="E-undated", result=True)    # undated sorts last
    got = [m.event_ticker for m in crud.get_completed_markets(db)]
    assert got == ["E-new", "E-old", "E-undated"]


def test_search_markets(db):
    add_meta(db, "fresh", title="Will Sinner win?", open_time=NOW - timedelta(hours=2))
    add_meta(db, "stale-unresolved", title="Will Sinner lose?", open_time=NOW - timedelta(days=3))
    add_meta(db, "stale-resolved", title="Sinner again", open_time=NOW - timedelta(days=3), result=True)
    add_meta(db, "no-open", title="Sinner none", open_time=None)
    add_meta(db, "other", title="Will Alcaraz win?", open_time=NOW)
    got = {m.ticker for m in crud.search_markets(db, "sinner")}
    assert got == {"fresh", "stale-resolved", "no-open"}


# ---- snapshots ----

def _tick(make_tick, market, price, **kw):
    return make_tick(market=market, price=price, **kw)


def test_bulk_insert_and_read_back(db, make_tick):
    crud.bulk_insert_ticks(
        db, [_tick(make_tick, "A", 0.4), _tick(make_tick, "B", 0.6)],
        model_by_ticker={"A": 0.45}, score_by_ticker={"A": '{"x":1}'},
    )
    rows = {r.ticker: r for r in db.query(market_snapshots).all()}
    assert rows["A"].model_price == 0.45 and rows["A"].score_state == '{"x":1}'
    assert rows["B"].model_price is None and rows["B"].score_state is None
    assert rows["A"].last_price == 0.4 and rows["A"].yes_bid == 0.49
    assert sorted(crud.get_all_seeded_tickers(db)) == ["A", "B"]


def test_get_snapshots_returns_oldest_first_within_limit(db, make_tick):
    for i, price in enumerate((0.1, 0.2, 0.3)):
        db.add(market_snapshots(ticker="A", last_price=price, snapshot_time=NOW + timedelta(seconds=i)))
    db.commit()
    assert [r.last_price for r in crud.get_snapshots(db, "A", limit=2)] == [0.2, 0.3]


def test_get_latest_prices_takes_newest_row_per_ticker(db):
    db.add_all([market_snapshots(ticker="A", last_price=p, snapshot_time=NOW) for p in (0.1, 0.2)])
    db.add(market_snapshots(ticker="B", last_price=0.9, snapshot_time=NOW))
    db.commit()
    assert crud.get_latest_prices(db, ["A", "B", "C"]) == {"A": 0.2, "B": 0.9}
    assert crud.get_latest_prices(db, []) == {}


# ---- links and events ----

def test_upsert_market_link_inserts_then_updates(db):
    crud.upsert_market_link(db, "T1", 10, 1, "H", "A")
    crud.upsert_market_link(db, "T1", 11, 2, "H2", "A2")
    links = crud.get_all_market_links(db)
    assert len(links) == 1
    assert (links[0].event_id, links[0].side, links[0].home, links[0].away) == (11, 2, "H2", "A2")


def test_insert_match_event(db):
    crud.insert_match_event(db, 5, NOW, "{}")
    assert db.query(match_events).one().event_id == 5


# ---- retention (gated on open_time; close_time is irrelevant) ----

def test_purge_snapshots_removes_only_old_rows(db):
    db.add_all([
        market_snapshots(ticker="A", snapshot_time=NOW - timedelta(days=8)),
        market_snapshots(ticker="A", snapshot_time=NOW - timedelta(days=1)),
    ])
    db.commit()
    assert crud.purge_snapshots(db) == 1
    assert db.query(market_snapshots).count() == 1


def test_purge_resolved_markets_cascades_but_keeps_match_events(db):
    old, far_future = NOW - timedelta(days=2), NOW + timedelta(days=14)
    # close_time is ~2 weeks out for every market, as on Kalshi: it must not matter.
    add_meta(db, "gone", result=True, open_time=old, close_time=far_future)
    add_meta(db, "kept-recent", result=True, open_time=NOW - timedelta(hours=5), close_time=far_future)
    add_meta(db, "kept-unresolved", result=None, open_time=old, close_time=far_future)
    add_meta(db, "kept-no-open-time", result=True, open_time=None, close_time=far_future)
    for t in ("gone", "kept-recent"):
        db.add(market_snapshots(ticker=t, snapshot_time=NOW))
        db.add(market_links(ticker=t, event_id=1, side=1))
    db.add(match_events(event_id=1, ts=NOW, state_json="{}"))
    db.commit()

    assert crud.purge_resolved_markets(db) == 1
    assert {m.ticker for m in db.query(market_meta)} == {"kept-recent", "kept-unresolved", "kept-no-open-time"}
    assert {s.ticker for s in db.query(market_snapshots)} == {"kept-recent"}
    assert {link.ticker for link in db.query(market_links)} == {"kept-recent"}
    assert db.query(match_events).count() == 1
