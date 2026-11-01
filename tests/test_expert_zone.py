"""Expert zone (srs_app/expert_zone.py, Eyal 2026-11-01): base-top level of the last breakout, zone wick -> body,
validity checks, transparent 0-100 score. Synthetic weekly paths -> one daily bar per weekday."""
import json
from datetime import date, timedelta

from srs_app import expert_zone as E


def daily(weeks, start=date(2023, 1, 2), vol=None):
    """weeks = [(open, high, low, close)] -> Mon..Fri daily rows; Mon opens, Tue high, Wed low, Fri closes."""
    rows, d = [], start
    for i, (o, h, l, c) in enumerate(weeks):
        v = (vol[i] if vol else 1000) / 5
        m = (o + c) / 2
        for k in range(5):
            day = d + timedelta(days=k)
            oo = o if k == 0 else m
            cc = c if k == 4 else m
            hh = h if k == 1 else max(oo, cc)
            ll = l if k == 2 else min(oo, cc)
            rows.append([day.isoformat(), oo, hh, ll, cc, v])
        d += timedelta(days=7)
    return rows


def rally(n, a, b):
    """n weeks drifting from a to b, 2-point ranges (ATR ~ 2-3)."""
    out = []
    for i in range(n):
        c = a + (b - a) * (i + 1) / n
        o = a + (b - a) * i / n
        out.append((o, max(o, c) + 1, min(o, c) - 1, c))
    return out


def base_path(pull_to=101.0, after=None):
    """uptrend -> 12-week base under 100 (top 100 twice) -> breakout close 104 -> run to 115 -> pullback to pull_to."""
    w = rally(30, 60, 92)
    base = [(92, 100, 91, 97), (97, 99, 93, 94), (94, 97, 92, 95), (95, 98, 93, 96), (96, 100, 94, 98),
            (98, 99, 95, 96), (96, 98, 93, 95), (95, 97, 92, 96), (96, 98.5, 94, 97), (97, 99, 95, 98),
            (98, 99.2, 96, 98.5), (98.5, 99.5, 97, 99)]
    bo = [(99, 105, 98.5, 104)]
    run = rally(5, 104, 115)
    pb = rally(4, 115, pull_to)
    return w + base + bo + run + pb + (after or [])


def test_zone_is_base_top_wick_to_body():
    rows = daily(base_path())
    r = E.find(rows)
    assert r["ok"], r
    assert r["top"] == 100.0                      # highest wick of the base
    assert r["bottom"] < r["top"]
    A = r["atr_w"]
    assert 0.25 * A - 1e-6 <= r["top"] - r["bottom"] <= 0.5 * A + 1e-6   # width sanity
    assert r["breakout_week"] == (date(2023, 1, 2) + timedelta(weeks=42)).isoformat()
    assert 0 <= r["score"] <= 100
    assert r["score"] == round(sum(f["pts"] for f in r["factors"]))
    assert {f["k"] for f in r["factors"]} == {"time", "touches", "volume", "breakout", "retest", "recency", "round", "gap", "below", "confluence"}
    assert sum(f["max"] for f in r["factors"]) == 100
    assert all(f["src"] for f in r["factors"])
    t = {f["k"]: f for f in r["factors"]}
    n = int(t["touches"]["val"])
    assert n >= 2 and t["touches"]["pts"] == (15 if n >= 3 else 10)     # top visited more than once (separate runs)
    assert t["round"]["pts"] == 5                                         # 100 is round
    assert t["retest"]["val"] == "#1"


def test_broken_level_gives_no_expert_level():
    rows = daily(base_path(pull_to=90.0))   # weekly closes > 3% under the zone
    r = E.find(rows)
    assert not r["ok"] and "broken" in r["reason"]


def test_no_pullback_yet():
    path = base_path()[:-4] + rally(2, 115, 116)
    r = E.find(daily(path))
    assert not r["ok"] and "no pullback" in r["reason"]


def test_never_moved_away():
    w = rally(30, 60, 92)
    base = [(92, 100, 91, 97)] + [(97, 99, 93, 96)] * 8
    path = w + base + [(96, 101, 95, 100.5), (100.5, 101, 99, 100)]
    r = E.find(daily(path))
    assert not r["ok"]


def test_breakout_volume_counts_in_score():
    p = base_path()
    v = [1000] * len(p)
    v[42] = 3000                                    # breakout week 3x the 10-week average
    r = E.find(daily(p, vol=v))
    b = {f["k"]: f for f in r["factors"]}["breakout"]
    assert b["pts"] >= 10 and "x3.00" in b["val"]


def test_running_week_not_used_for_structure():
    rows = daily(base_path())
    rows = rows[:-2]                                  # last week ends on a Wednesday -> partial
    assert not E.week_complete(rows[-1][0])
    r = E.find(rows)
    assert r["ok"] and r["top"] == 100.0


def test_overlap_and_round_step():
    assert E.overlap(10, 9, 9.5, 8) is True
    assert E.overlap(10, 9, 8.9, 8) is False
    assert E.overlap(10, 9, None, None) is None
    assert E.round_step(12) == 1 and E.round_step(60) == 5 and E.round_step(300) == 10 and E.round_step(700) == 50


def test_build_writes_only_requested(tmp_path):
    (tmp_path / "candles").mkdir()
    (tmp_path / "candles" / "AAA.json").write_text(json.dumps({"d": daily(base_path())}))
    p = E.write(["AAA", "ZZZ"], tmp_path)
    doc = json.loads(p.read_text())
    assert doc["rule_version"] == E.RULE_VERSION
    assert set(doc["tickers"]) == {"AAA", "ZZZ"}
    assert doc["tickers"]["AAA"]["ok"] and doc["tickers"]["ZZZ"] == {"ok": False, "reason": "no candles"}
    assert E.refresh(tmp_path) == p and set(json.loads(p.read_text())["tickers"]) == {"AAA", "ZZZ"}


def test_follows_the_starred_list(tmp_path, monkeypatch):
    (tmp_path / "candles").mkdir()
    for t in ("AAA", "BBB", "CCC"):
        (tmp_path / "candles" / f"{t}.json").write_text(json.dumps({"d": daily(base_path())}))
    st = tmp_path / "app_state.json"
    st.write_text(json.dumps({"watchlist": ["AAA", "BBB"]}))
    p = E.sync_starred(tmp_path, state_path=str(st))
    assert set(json.loads(p.read_text())["tickers"]) == {"AAA", "BBB"}
    st.write_text(json.dumps({"watchlist": ["BBB", "CCC"]}))          # AAA unstarred, CCC starred
    E.sync_starred(tmp_path, state_path=str(st))
    assert set(json.loads(p.read_text())["tickers"]) == {"BBB", "CCC"}
    st.write_text(json.dumps({}))                                      # no list synced -> keep the file's set
    E.sync_starred(tmp_path, state_path=str(st))
    assert set(json.loads(p.read_text())["tickers"]) == {"BBB", "CCC"}


def test_add_and_remove_merge(tmp_path, monkeypatch):
    (tmp_path / "candles").mkdir()
    (tmp_path / "candles" / "AAA.json").write_text(json.dumps({"d": daily(base_path())}))
    E.write(["AAA"], tmp_path)
    monkeypatch.setattr(E, "_yf_rows", lambda t: daily(base_path()) if t == "NEW" else None)
    p = E.add(["new"], tmp_path)
    doc = json.loads(p.read_text())["tickers"]
    assert set(doc) == {"AAA", "NEW"} and doc["NEW"]["ok"]            # no app candles -> downloaded in memory
    assert not (tmp_path / "candles" / "NEW.json").exists()
    E.remove(["AAA"], tmp_path)
    assert set(json.loads(p.read_text())["tickers"]) == {"NEW"}


def test_kbwb_five_closes_under_the_zone_is_broken():
    """Regression (Eyal 2026-11-01): KBWB closed under its expert-zone bottom 89.02 for 5 straight weeks (lows 86.78)
    and stayed valid with score 82 under v1. Two consecutive closes under the bottom now break it: no expert level at
    89.02-89.94 (an older valid level is allowed)."""
    from pathlib import Path
    rows = json.loads((Path(__file__).parent / "data" / "kbwb_daily_20261030.json").read_text())["d"]
    r = E.find(rows, asof="2026-11-01")
    assert not (r["ok"] and r["bottom"] == 89.02 and r["top"] == 89.94), r
    if r["ok"]:
        assert r["top"] < 89.02


def _with_closes_below(n_below):
    """base_path pulled back into the zone, then n_below weekly closes under the zone bottom, then back inside."""
    p = base_path(pull_to=100.5)
    r0 = E.find(daily(p))
    bot = r0["bottom"]
    under = [(bot + 0.2, bot + 0.3, bot - 1.2, bot - 0.4)] * n_below
    back = [(bot - 0.4, r0["top"] + 0.2, bot - 0.5, bot + 0.3)]
    return E.find(daily(p + under + back)), r0


def test_single_close_below_is_flagged_with_penalty():
    r, r0 = _with_closes_below(1)
    assert r["ok"] and r["top"] == r0["top"]
    assert len(r["warnings"]) == 1 and r["warnings"][0]["he"].startswith("סגירה שבועית מתחת לאזור")
    below = {f["k"]: f for f in r["factors"]}["below"]
    assert below["pts"] == -10 and below["val"] == r["warnings"][0]["date"]


def test_two_consecutive_closes_below_break_the_level():
    r, r0 = _with_closes_below(2)
    assert not (r["ok"] and r["top"] == r0["top"])
    if not r["ok"]:
        assert "broken" in r["reason"]


def test_sync_all_covers_every_exported_ticker_and_stars(tmp_path, monkeypatch):
    (tmp_path / "candles").mkdir()
    for t in ("AAA", "BBB"):
        (tmp_path / "candles" / f"{t}.json").write_text(json.dumps({"d": daily(base_path())}))
    (tmp_path / "candles" / "BAD.json").write_text('{"d": [["x"]]}')           # broken file -> reason, not a crash
    st = tmp_path / "app_state.json"
    st.write_text(json.dumps({"watchlist": ["OUT"]}))                        # starred, outside the universe
    monkeypatch.setattr(E, "_yf_rows", lambda t: daily(base_path()) if t == "OUT" else None)
    doc = json.loads(E.sync_all(tmp_path, state_path=str(st)).read_text())
    assert set(doc["tickers"]) == {"AAA", "BBB", "BAD", "OUT"}
    assert doc["tickers"]["OUT"]["ok"] and doc["tickers"]["AAA"]["ok"]
    assert doc["tickers"]["BAD"]["ok"] is False and doc["tickers"]["BAD"]["reason"]
    f = doc["tickers"]["AAA"]["factors"][0]
    assert set(f) == {"k", "pts", "max", "val"} and doc["labels"][f["k"]] and doc["sources"][f["k"]]   # slim file


def test_expert_trade_entry_sl_tp():
    r = E.find(daily(base_path()))
    tr = r["trade"]
    assert tr["entry"] == r["top"]                                   # Bulkowski: close back above the pattern top
    assert tr["sl"] < min(r["bottom"], tr["retest_low"])             # under the retest low and the zone
    assert tr["sl"] <= tr["entry"] - r["atr_w"] + 0.01                # never tighter than 1 weekly ATR
    assert tr["tp"] == r["post_high"]                                # IBD: the pre-pullback high
    assert abs(tr["rr"] - (tr["tp"] - tr["entry"]) / (tr["entry"] - tr["sl"])) < 0.02
    assert tr["tp_mm"] > r["top"] and isinstance(tr["confirmed"], bool)


def test_falling_30_week_ma_is_not_a_retest():
    """Stage 3/4 (Weinstein): a spike then a crash back to the old base top is not a retest even if the base held."""
    path = base_path()[:-4] + rally(3, 115, 200) + [(200, 201, 199, 200)] * 20 + rally(12, 200, 102)
    r = E.find(daily(path))
    assert not r["ok"] and r["reason"].startswith("30-week MA falling")


def test_gpix_stop_is_one_weekly_atr_not_four_percent():
    """GPIX (weekly ATR ~1.06): the 1-weekly-ATR minimum stop (53.48, not the old 4% 52.36) is checked on the synthetic
    trade test. Since v5 (Eyal 2026-11-01, KBWB) GPIX has NO expert level: its breakouts never rallied 2 ATR away, so
    there is no retest (a covered-call ETF that barely trends)."""
    r = E.find(_fixture("gpix_daily_20261030.json"), asof="2026-11-01")
    assert not r["ok"] and r["reason"].startswith("never moved away"), r


def test_stld_moves_up_to_the_higher_shelf():
    """Regression (Eyal 2026-11-01, v4/v5): STLD broke out over 201.31-207.36 in April 2026. Support at ~216-219 was
    touched, price rallied >= 2 ATR away for >= 4 weeks (to 288 in June, to 273 in August) and came back: 5/18 (218.53),
    6/29 (216.36), 8/17 (217.5; 9/28 219.1 is the same pullback, no 2-ATR rally between). Active zone = that shelf;
    the breakout level is kept as the origin."""
    r = E.find(_fixture("stld_daily_20261030.json"), asof="2026-11-01")
    assert r["ok"], r
    assert abs(r["bottom"] - 216.36) < 0.05 and 219.5 < r["top"] < 222.5, r
    assert r["origin"]["top"] == 207.36 and r["origin"]["bottom"] == 201.31
    lows = dict((d, l) for d, l in r["shelf"]["lows"])
    assert lows.get("2026-06-29") == 216.36 and lows.get("2026-08-17") == 217.5 and len(lows) == 3
    assert any(a <= "2026-09-28" <= b for a, b in r["shelf"]["episodes"])    # 9/28 inside the 8/17 episode
    assert r["shelf"]["closes_in"]                                          # bodies, not wicks only
    tr = r["trade"]
    assert tr["entry"] == r["top"] and tr["sl"] <= r["bottom"] - 0.1 * r["atr_w"] + 0.01
    assert tr["sl"] <= tr["entry"] - r["atr_w"] + 0.01 and tr["tp"] == r["post_high"]
    touches = next(f for f in r["factors"] if f["k"] == "touches")
    assert touches["pts"] == 15 and touches["val"].startswith("3")


def test_no_shelf_without_two_higher_lows():
    """The synthetic base path has no higher shelf: the zone stays at the breakout level, origin == zone."""
    r = E.find(daily(base_path()))
    assert r["ok"] and r["shelf"] is None and r["origin"]["top"] == r["top"]


def test_hammer_shapes():
    assert E.hammer_shape(10, 10.2, 8, 10.1) == "H"          # long lower shadow, body on top, tiny upper shadow
    assert E.hammer_shape(10, 10.6, 8.8, 10.3) == "h"        # lower shadow 1.2 = 4x body, 67% of range, close upper half
    assert E.hammer_shape(10, 12, 9.9, 11.9) is None         # big up body
    assert E.hammer_shape(10, 10, 10, 10) is None
    assert E.touches(9.6, 10.1, 10, 9.5, 1.0) and not E.touches(10.6, 11, 10, 9.5, 1.0)
    assert not E.touches(8.8, 9.0, 10, 9.5, 1.0) and E.touches(8.8, 9.6, 10, 9.5, 1.0)


def _fixture(name):
    from pathlib import Path
    return json.loads((Path(__file__).parent / "data" / name).read_text())["d"]


def test_asb_hammers_on_the_expert_zone():
    """ASB (Eyal 2026-11-01, scan /workspace/asb_like): 3 hammer weeks on the expert zone in the last 6 completed weeks,
    no weekly close under the zone -> matches the default filter (N=2, X=6)."""
    r = E.find(_fixture("asb_daily_20261030.json"), asof="2026-11-01")
    assert r["ok"] and r["last_week"] == "2026-10-26"
    h6 = [(x["w"], x["s"]) for x in r["hammers"] if x["k"] <= 6]
    assert sorted(h6) == [("2026-09-21", "h"), ("2026-09-28", "H"), ("2026-10-12", "h")]
    assert not [k for k in r["closes_below_k"] if k <= 6]


def test_tgt_hammers_on_the_shelf_zone():
    """TGT: the 150-154 lows (10/5-10/26) are ONE pullback from the 170 high, no 2-ATR rally between them -> not a shelf
    (v5). The zone is the breakout level 140.23-143.30; the 10/26 textbook hammer (low 145.32) touches it."""
    r = E.find(_fixture("tgt_daily_20261030.json"), asof="2026-11-01")
    assert r["ok"] and r["shelf"] is None and (r["bottom"], r["top"]) == (140.23, 143.3), r
    assert {x["w"]: x["s"] for x in r["hammers"] if x["k"] <= 6} == {"2026-10-26": "H"}
    assert all(x["k"] <= E.HAMMER_WEEKS for x in r["hammers"])


def test_refresh_stale_refreshes_only_exported_stale_tickers():
    """Candles froze for tickers that dropped out of the day's FinViz screen (ASB/STLD/MRK, 2026-11-01)."""
    import pandas as pd
    from srs_app import export_data as X
    idx = lambda end: pd.date_range(end=end, periods=5, freq="B")
    mk = lambda end: pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=idx(end))
    hist = {"OLD": mk("2026-10-22"), "NEW": mk("2026-10-30"), "OTHER": mk("2026-10-01")}
    seen = {}
    def fake(sub, ts):
        seen["t"] = sorted(ts)
        return {t: mk("2026-10-30") for t in ts}
    got = X.refresh_stale(hist, ["OLD", "NEW", "MISSING"], target=pd.Timestamp("2026-10-30"), refresh=fake)
    assert got == ["OLD"] and seen["t"] == ["OLD"]
    assert hist["OLD"].index.max() == pd.Timestamp("2026-10-30") and hist["OTHER"].index.max() == pd.Timestamp("2026-10-01")



def test_kbwb_pullback_lows_are_not_a_shelf():
    """Regression (Eyal 2026-11-01, v5 rejects v4): KBWB 9/28 low 85.1 and 10/12 low 84.3 are two wicks of the SAME
    pullback (the bounce between reached 89.04, under 2 ATR; closes 86.8-87.6): a base forming now, not a retest.
    No shelf; the June breakout level 89.02-89.94 is broken (two closes under), so KBWB has no expert level."""
    r = E.find(_fixture("kbwb_daily_20261030.json"), asof="2026-11-01")
    assert not r["ok"] and "broken" in r["reason"], r


def test_shelf_needs_a_rally_between_touches():
    """Two lows at the same price inside one pullback (bounce < 2 ATR) are one touch; after a 2-ATR rally lasting
    >= 4 weeks the return counts as a second touch."""
    W = [{"open": 100, "high": 101, "low": 99, "close": 100.5, "time": f"w{i}"} for i in range(40)]
    A = 1.0
    z = {"top": 90.0}
    for k, lo in ((20, 95.0), (24, 95.2)):                       # same pullback: bounce to 97 only
        W[k] = {"open": 96, "high": 97, "low": lo, "close": 96.2, "time": f"w{k}"}
    for k in range(21, 24):
        W[k] = {"open": 96.5, "high": 97, "low": 96.3, "close": 96.8, "time": f"w{k}"}
    for k in range(25, 40):
        W[k] = {"open": 97, "high": 97.5, "low": 96.4, "close": 97, "time": f"w{k}"}
    assert E._shelf(W, W, 5, z, A, 97) is None
    for k in range(26, 32):                                      # rally to 99 (> top0 + 2 A) for 6 weeks, then back
        W[k] = {"open": 98, "high": 99.5, "low": 97.5, "close": 99, "time": f"w{k}"}
    W[33] = {"open": 96, "high": 96.8, "low": 95.1, "close": 95.9, "time": "w33"}
    sh = E._shelf(W, W, 5, z, A, 97)
    assert sh and len(sh["episodes"]) == 2 and abs(sh["bottom"] - 95.0) < 1e-9
