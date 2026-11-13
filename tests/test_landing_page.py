from types import SimpleNamespace as NS

from app.services import landing_page as lp


def market(ticker, event, title="Will A B win?", result=None):
    return NS(ticker=ticker, event_ticker=event, title=title, open_time="2026-01-01", result=result)


def test_clean_float():
    assert lp.clean_float(float("nan")) is None
    assert lp.clean_float(None) is None
    assert lp.clean_float(0.0) == 0.0


def test_group_keeps_only_pairs_in_first_seen_order():
    rows = [market("a1", "E1"), market("b1", "E2"), market("a2", "E1"), market("c1", "E3"), market("c2", "E3")]
    out = lp.group_into_matches(
        rows,
        new_event=lambda m: {"event_ticker": m.event_ticker, "players": []},
        player=lambda m: {"ticker": m.ticker},
    )
    assert [e["event_ticker"] for e in out] == ["E1", "E3"]


def test_group_skip_and_limit():
    rows = [market(f"{e}{i}", e) for e in ("E1", "E2", "E3") for i in (1, 2)]
    kw = dict(new_event=lambda m: {"players": []}, player=lambda m: {"ticker": m.ticker})
    assert len(lp.group_into_matches(rows, limit=2, **kw)) == 2
    # Skipping one half of E1 leaves a lone player, so the event is dropped.
    out = lp.group_into_matches(rows, skip=lambda m: m.ticker == "E11", **kw)
    assert len(out) == 2


def test_build_live_orders_home_first_and_requires_two(make_state):
    state = make_state(home="Home", away="Away")
    cands = [(1, state, [("T-AWAY", 2), ("T-HOME", 1)]), (2, state, [("T-ONLY", 1)])]
    live = lp.build_live(cands, {"T-HOME": 0.6})
    assert len(live) == 1
    assert [p["name"] for p in live[0]["players"]] == ["Home", "Away"]
    assert live[0]["players"][0]["price"] == 0.6 and live[0]["players"][1]["price"] is None


def test_live_candidates_and_links():
    by_event = lp.links_by_event({"t1": (1, 1), "t2": (1, 2), "t3": (9, 1)})
    assert by_event == {1: [("t1", 1), ("t2", 2)], 9: [("t3", 1)]}
    cands = lp.live_candidates({1: "s1", 2: "s2"}, by_event)
    assert cands == [(1, "s1", [("t1", 1), ("t2", 2)])]


def test_build_upcoming_excludes_live_events():
    rows = [market("t1", "E1"), market("t2", "E1"), market("u1", "E2"), market("u2", "E2")]
    out = lp.build_upcoming(rows, {"u1": 0.4}, {"t1": (7, 1), "t2": (7, 2)}, live_event_ids={7}, limit=10)
    assert [e["event_ticker"] for e in out] == ["E2"]
    assert out[0]["players"][0]["price"] == 0.4


def test_build_completed_has_won_flag():
    rows = [market("KXATPMATCH-26JAN05AAABBB-AAA", "C1", result=True),
            market("KXATPMATCH-26JAN05AAABBB-BBB", "C1", result=False)]
    out = lp.build_completed(rows, 5)
    assert [p["won"] for p in out[0]["players"]] == [True, False]
    assert "match_date" in out[0]


def test_snapshot_to_dict_cleans_nan_and_keeps_order():
    row = NS(snapshot_time="t", volume_1s=1, volume_10s=2, volume_60s=3,
             **{f: float("nan") for f in lp.SNAPSHOT_FIELDS if not f.startswith("volume")})
    out = lp.snapshot_to_dict(row)
    assert list(out) == ["snapshot_time", *lp.SNAPSHOT_FIELDS]
    assert out["last_price"] is None and out["volume_10s"] == 2


def test_score_payload(make_state):
    assert lp.score_payload(None, None, None) == {"mapped": False}
    assert lp.score_payload((1, 1), None, None) == {"mapped": False}
    out = lp.score_payload((1, 2), make_state(), {"model_price": 0.6, "edge": 0.1})
    assert out["mapped"] and out["side"] == 2
    assert (out["model_price"], out["market_price"], out["edge"]) == (0.6, None, 0.1)
    assert lp.score_payload((1, 1), make_state(), None)["model_price"] is None
