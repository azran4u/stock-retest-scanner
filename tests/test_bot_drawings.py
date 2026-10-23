"""Bot drawings: v3d golden regression (levels must reproduce), candidate selection, SQL format."""
import json
from pathlib import Path

import pytest

from srs_app import bot_drawings as B
from srs_app.sync import sql_insert_bot_drawing

GOLDEN = Path(__file__).parent / "golden"
GOLD = json.loads((GOLDEN / "bot_drawings_golden.json").read_text())["rows"]


@pytest.fixture(scope="module")
def rules_on_fixture(tmp_path_factory):
    """Run the vendored v3d rules (srs_app/v3d) on the committed price fixture: never skips, never reads /workspace."""
    import os
    import sys
    import pandas as pd
    df = pd.read_csv(GOLDEN / "hist_golden.csv.gz", parse_dates=["date"])
    H = {t: g.drop(columns="ticker").set_index("date") for t, g in df.groupby("ticker")}
    pk = tmp_path_factory.mktemp("hist") / "hist.pkl"
    pd.to_pickle(H, pk)
    saved = {k: os.environ.get(k) for k in ("SRS_HIST_CACHE", "SRS_TV_DRAWINGS")}
    os.environ.update(SRS_HIST_CACHE=str(pk), SRS_TV_DRAWINGS=str(GOLDEN / "tv_drawings_min.json"))
    mods = {m: sys.modules.pop(m) for m in ("infer", "infer_v2", "infer_v3", "infer_v3d") if m in sys.modules}
    old_dir, old_r = B.LEARN_DIR, dict(B._R)
    B.LEARN_DIR = Path(B.__file__).resolve().parent / "v3d"
    B._R.clear()
    yield B
    B._R.clear(); B._R.update(old_r); B.LEARN_DIR = old_dir
    for m in ("infer", "infer_v2", "infer_v3", "infer_v3d"):
        sys.modules.pop(m, None)
    sys.modules.update(mods)
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.mark.parametrize("g", GOLD, ids=[g["ticker"] for g in GOLD])
def test_v3d_golden(g, rules_on_fixture):
    r = rules_on_fixture.compute(g["ticker"], g["data_date"])
    if g.get("expect_no_level"):  # retired by a later rule fix (kept so the change stays visible)
        assert not r["has_level"] and "price ran away" in r["reason"], r
        return
    assert r["has_level"]
    if g.get("his_zone"):  # app feedback case: the bot zone must overlap the zone he drew himself
        lo, hi = g["his_zone"]
        assert r["zone_bottom"] < hi and r["zone_top"] > lo, (r["zone_bottom"], r["zone_top"], g["his_zone"])
    for a, b in (("zone_bottom", "zone_bottom"), ("zone_top", "zone_top"), ("entry", "entry"), ("stop", "sl"), ("target", "tp")):
        assert abs(r[a] - g[b]) < 0.02, (a, r[a], g[b])
    assert r["why"]["branch"] == g["kind"] and r["why"]["pivot_date"] == g["pivot_date"]
    # Long Position time anchor: the week after the last candle, 20 weekly bars wide
    assert r["t_start"] > g["data_date"] and len(r["t_end"]) == 10


REP = {"f_dollar_vol": True, "f_history": True, "f_no_earnings_14d": True, "f_technical": True}


def test_plan_selection():
    rows = [dict(REP, ticker=t) for t in ("NEW", "MINE", "TVD", "NI", "STRUCT", "BOTOK", "BOTBROKE", "REJ", "REJOLD")]
    rows.append(dict(REP, ticker="LOWVOL", f_dollar_vol=False))
    rows.append(dict(REP, ticker="NOTECH", f_technical=False))
    rows.append(dict(REP, ticker="LINES", tv_source="user-lines"))
    dr = [
        {"id": "1", "ticker": "MINE", "kind": "zone", "source": "user", "status": "active"},
        {"id": "2", "ticker": "TVD", "kind": "long", "source": "tv", "status": "active", "stop": 1},
        {"id": "3", "ticker": "BOTOK", "kind": "long", "source": "bot", "status": "active", "stop": 10, "created_at": "2026-10-01"},
        {"id": "4", "ticker": "BOTBROKE", "kind": "long", "source": "bot", "status": "active", "stop": 10, "created_at": "2026-10-01"},
        {"id": "5", "ticker": "BOTBROKE", "kind": "zone", "source": "bot", "status": "active", "created_at": "2026-10-01"},
        {"id": "6", "ticker": "REJ", "kind": "zone", "source": "bot", "status": "rejected", "meta": {"rule_version": B.RULE_VERSION}},
        {"id": "7", "ticker": "REJOLD", "kind": "zone", "source": "bot", "status": "rejected", "meta": '{"rule_version": "v0"}'},
    ]
    labels = [{"ticker": "NI", "label": "not_interesting", "value": "yes", "until": "2026-12-01"}]
    fb = [{"ticker": "STRUCT", "category": "structure", "created_at": "2026-10-20T10:00:00+00:00"}]
    lows = {"BOTOK": 11.0, "BOTBROKE": 9.5}
    p = B.plan(rows, dr, labels, fb, today="2026-10-23", low_fn=lambda t, since: lows.get(t))
    assert sorted(p["draw"]) == ["BOTBROKE", "NEW", "REJOLD"]
    assert sorted(p["obsolete"]["BOTBROKE"]) == ["4", "5"]
    assert p["skip"] == {"LINES": "his own Fib / horizontal lines (user-lines)", "NI": "not interesting", "STRUCT": "structure feedback < 8w", "BOTOK": "live bot drawing",
                         "REJ": "rejected under the current rule version"}
    # structure feedback expires after 8 weeks
    p2 = B.plan([dict(REP, ticker="STRUCT")], [], [], fb, today="2026-12-31", low_fn=lambda *a: None)
    assert p2["draw"] == ["STRUCT"]


def test_sql_insert_bot_is_active_with_meta():
    q = sql_insert_bot_drawing("abc", "long", entry=10, stop=9, target=13, t_start="2026-10-26", t_end="2027-03-15",
                               note="BOT", meta={"rule_version": "v", "why": {"a": "it's"}})
    assert "'bot'" in q and "'active'" in q and "'2027-03-15'" in q
    assert q.count("::jsonb") == 1 and "it''s" in q and q.startswith("insert into public.drawings (ticker")


def test_bot_rows_count_by_default():
    from srs_app.app_drawings import build_store
    from report_filters import drawing_source
    rows = [
        {"id": "z", "ticker": "AAA", "kind": "zone", "zone_top": 11, "zone_bottom": 10, "source": "bot", "status": "active"},
        {"id": "l", "ticker": "AAA", "kind": "long", "entry": 10.9, "stop": 9.9, "target": 14, "source": "bot", "status": "active"},
        {"id": "r", "ticker": "BBB", "kind": "zone", "zone_top": 5, "zone_bottom": 4, "source": "bot", "status": "rejected"},
        {"id": "u", "ticker": "CCC", "kind": "zone", "zone_top": 5, "zone_bottom": 4, "source": "user", "status": "active"},
    ]
    st = build_store(rows)
    assert st["AAA"]["source_override"] == "user" and st["AAA"]["bot_drawn"] is True and st["AAA"]["rr"] == 3.1
    assert "BBB" not in st  # rejected (negative feedback) never counts
    assert "bot_drawn" not in st["CCC"]
    src = drawing_source("AAA", st["AAA"], registry={}, approved={})
    assert src["tv_source"] == "bot-approved" and src["f_bot_review"] is False


def test_plan_retires_target_hit_and_far_bot_drawings():
    """BMO / RY 2026-10-23: a live bot drawing is obsolete also when the close reached TP or ran > 3 ATR above the
    zone (same rules as the report's obsolete check); outside the candidate list it is only retired, never redrawn;
    his own drawing next to it is never touched."""
    rows = [dict(REP, ticker=t) for t in ("OK", "TP", "FAR")] + [dict(REP, ticker="GONE", f_technical=False)]
    def bot(i, t, **k):
        return dict(id=i, ticker=t, source="bot", status="active", created_at="2026-10-05", **k)
    dr = [bot("1", "OK", kind="zone", zone_top=100), bot("2", "OK", kind="long", stop=90, target=130),
          bot("3", "TP", kind="long", stop=90, target=110), bot("4", "FAR", kind="zone", zone_top=100),
          bot("5", "FAR", kind="long", stop=90, target=200), bot("6", "GONE", kind="long", stop=90, target=110),
          bot("7", "MINE", kind="long", stop=90, target=110),
          {"id": "8", "ticker": "MINE", "kind": "zone", "source": "user", "status": "active"}]
    px = {"OK": (120.0, 10.0), "TP": (111.0, 10.0), "FAR": (131.0, 10.0), "GONE": (115.0, 10.0), "MINE": (112.0, 10.0)}
    p = B.plan(rows, dr, [], [], today="2026-10-23", low_fn=lambda t, s: 95.0, price_fn=px.get)
    assert sorted(p["draw"]) == ["FAR", "TP"]
    assert p["why_obsolete"] == {"TP": ["target hit"], "FAR": ["far"], "GONE": ["target hit"], "MINE": ["target hit"]}
    assert p["obsolete"]["MINE"] == ["7"] and p["skip"]["OK"] == "live bot drawing"


def test_far_cap_matches_obsolete_rule():
    import report_filters as rf
    assert B.FAR_CAP_ATR == float(rf.CONFIG["stale_far_atr"])


def test_despike_lows_only_isolated_wicks():
    """HWC 2026-10-14: a lone 6-point wick with open/close near the high is clipped; normal bars and real
    multi-day drops are left alone (app feedback cmd 5)."""
    import pandas as pd
    idx = pd.bdate_range("2026-09-01", periods=30)
    base = [70 + 0.1 * i for i in range(30)]
    d = pd.DataFrame({"Open": base, "High": [b + 1 for b in base], "Low": [b - 1 for b in base],
                      "Close": [b + 0.5 for b in base], "Volume": 1e6}, index=idx)
    d.iloc[25, d.columns.get_loc("Low")] = d["Low"].iloc[25] - 7      # lone spike, recovers same day
    clean, sp = B.despike_lows(d)
    assert sp == [str(idx[25].date())] and clean["Low"].iloc[25] == min(d["Open"].iloc[25], d["Close"].iloc[25])
    assert d["Low"].iloc[25] < 70  # the input frame is not modified
    e = d.copy()
    e.iloc[26, e.columns.get_loc("Low")] = e["Low"].iloc[25]           # next day also trades down there: real move
    assert B.despike_lows(e)[1] == []


def test_qcom_reclaimed_level_and_swing_anchor(rules_on_fixture):
    """QCOM zone feedback (cmd 3, 2026-10-23): the Dec 2025 - Jan 2026 level broke in Jul-Aug 2026 and was reclaimed in
    Sep 2026; v3e must pick it (overlapping his 173.47-179.04), measuring the pullback from the 2026-09-25 swing high."""
    r = rules_on_fixture.compute("QCOM", "2026-10-22")
    assert r["has_level"] and r["why"]["reclaimed"] and r["why"]["swing_anchor"]
    assert r["zone_bottom"] < 179.04 and r["zone_top"] > 173.47
    B = rules_on_fixture
    old = (B.RECLAIM, B.SWING_ANCHOR, B.ZONE_SCORING)
    try:
        B.RECLAIM = B.SWING_ANCHOR = False  # v3d picked the deep August support 142.12-145.41
        B.ZONE_SCORING = "v3d"
        v = B.compute("QCOM", "2026-10-22")
        assert v["zone_top"] < 150
    finally:
        B.RECLAIM, B.SWING_ANCHOR, B.ZONE_SCORING = old


def test_twst_reclaimed_level_above_price_not_picked(rules_on_fixture):
    """TWST 2026-10-22 (close 135.47): the reclaimed 2026-08-21 level 145.59-155.44 sits above the price; a reclaimed
    level the price has fallen back under is no support (bottom <= close + ABOVE_PRICE_TOL_ATR x ATR)."""
    r = rules_on_fixture.compute("TWST", "2026-10-22")
    assert r["has_level"]
    assert r["zone_bottom"] <= r["price"] + rules_on_fixture.ABOVE_PRICE_TOL_ATR * r["why"]["atr"]
    assert not (abs(r["zone_bottom"] - 145.59) < 0.05 and abs(r["zone_top"] - 155.44) < 0.05)


def test_twst_recent_higher_low_is_the_zone(rules_on_fixture):
    """TWST zone feedback (cmd 6): in the run-up the last higher low before the 2026-10-09 high (2026-09-11 swing low,
    clarity 2) is the zone; it must overlap his current zone 115.7-121.2 and sit below the 135.47 close."""
    r = rules_on_fixture.compute("TWST", "2026-10-22")
    assert r["has_level"] and r["why"]["pivot_date"] == "2026-09-11" and r["why"]["touches_w"] >= 1
    assert r["zone_bottom"] < 121.2 and r["zone_top"] > 115.7 and r["zone_top"] <= r["price"]
    assert r["rr"] >= 2


def test_touch_count_and_recency():
    """v4 scoring helpers: consecutive touching bars are one touch; a close, low or high in the band counts."""
    import numpy as np
    lo = np.array([10.0, 9.9, 9.95, 12.0, 12.0, 10.1, 13.0])
    hi = lo + 0.5
    cl = lo + 0.3
    n, last = B.touches(lo, hi, cl, 10.0, 10.2, 0.05)
    assert n == 2 and last == 5
    assert B.touches(lo, hi, cl, 20, 21, 0.1) == (0, -1)


def test_touch_meta_stored(rules_on_fixture):
    r = rules_on_fixture.compute("QCOM", "2026-10-22")
    w = r["why"]
    for k in ("touches_w", "touches_d", "pivot_age_w", "weeks_since_touch", "alt_levels", "zone_scoring"):
        assert k in w
    assert w["zone_scoring"] == "touches" and w["touches_w"] >= 1
