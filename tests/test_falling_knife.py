"""Falling-knife gate (Eyal 2026-11-09): "when the last weekly candle was a healthy red candle on above-average volume we
do not enter even if price closed on the support; wait for next week's close so it is not a falling knife".

= f_no_red_vol_week, a CORE PASS gate again (info only 2026-10-26 .. 2026-11-09): last COMPLETED W-FRI weekly candle with
close < open, body >= 50% of the high-low range (a hammer / doji is never 'healthy'), and the week's average daily
volume > the average daily volume of the 30 trading days before it. Blocks PASS, the hot list's 'מוכנה' tier and the
entry alerts (supabase/functions/srs-price-alerts logic_test.ts); clears once the next weekly candle closes."""
from datetime import date

import numpy as np
import pandas as pd

import report_filters as rf
from srs_app import expert_watch as X
from srs_app import expert_zone as E
from srs_app import export_data as XD

FRI_AFTER = pd.Timestamp("2026-10-23 17:00", tz="America/New_York")
WED_NEXT = pd.Timestamp("2026-10-28 12:00", tz="America/New_York")
FRI_NEXT = pd.Timestamp("2026-10-30 17:00", tz="America/New_York")


def _week(o, c, h, l, vol, start):
    path = np.linspace(o, c, 6)
    rows = []
    for i in range(5):
        a, b = path[i], path[i + 1]
        rows.append([a, max(a, b), min(a, b), b, vol])
    rows[0][1] = h
    rows[-1][2] = l
    return pd.DataFrame(rows, index=pd.bdate_range(start, periods=5), columns=["Open", "High", "Low", "Close", "Volume"])


def _hist(*weeks):
    """12 flat weeks (100, vol 1M/day) to Fri 2026-10-16, then the given weeks from Mon 2026-10-19 on."""
    idx = pd.bdate_range(end="2026-10-16", periods=60)
    base = pd.DataFrame([[100.0, 101.0, 99.0, 100.0, 1_000_000.0]] * len(idx), index=idx,
                        columns=["Open", "High", "Low", "Close", "Volume"])
    starts = pd.date_range("2026-10-19", periods=len(weeks), freq="7D")
    return pd.concat([base] + [_week(*w, start=s) for w, s in zip(weeks, starts)]).astype(float)


HEALTHY_RED_LOUD = (100, 90, 100.5, 89.5, 2_000_000)   # body 10 / range 11 = 91%, 2x volume
RED_HAMMER_LOUD = (100, 99.5, 100.2, 90, 2_000_000)     # lower shadow 9.5 >= 2x body 0.5, upper 0.2: classic hammer
RED_QUIET = (100, 90, 100.5, 89.5, 800_000)             # healthy red body but volume 0.8x average


def _k(df, now):
    return rf.compute_red_vol_week(df, now.date(), now_et=now)


def test_healthy_red_high_volume_week_blocks():
    out = _k(_hist(HEALTHY_RED_LOUD), FRI_AFTER)
    assert out["f_no_red_vol_week"] is False and out["red_vol_week_date"] == "2026-10-23"
    assert out["red_vol_body_pct"] >= 50 and out["red_vol_ratio"] > 1
    assert "f_no_red_vol_week" in rf.CORE_FILTERS and "f_no_red_vol_week" not in rf.WARN_FILTERS
    base = {f: True for f in rf.CORE_FILTERS}
    r = rf.finalize_status({**base, "f_no_red_vol_week": out["f_no_red_vol_week"]})
    assert r["status"] == "FAIL" and r["failed_filters"] == "no_red_vol_week"


def test_red_hammer_is_not_healthy_red():
    d = _hist(RED_HAMMER_LOUD)
    w = d.loc["2026-10-19":]
    o, h, l, c = w["Open"].iloc[0], w["High"].max(), w["Low"].min(), w["Close"].iloc[-1]
    assert c < o and E.hammer_shape(o, h, l, c) == "H"          # it IS a (red) textbook hammer
    out = _k(d, FRI_AFTER)
    assert out["red_vol_ratio"] > 1 and out["red_vol_body_pct"] < 50
    assert out["f_no_red_vol_week"] is True


def test_red_low_volume_week_does_not_block():
    out = _k(_hist(RED_QUIET), FRI_AFTER)
    assert out["red_vol_body_pct"] >= 50 and out["red_vol_ratio"] < 1
    assert out["f_no_red_vol_week"] is True


def test_running_week_not_judged_and_block_clears_after_next_week_closes():
    d = _hist(HEALTHY_RED_LOUD, (90, 91, 92, 89.5, 1_000_000))
    # Wednesday of the next week: the running week is not judged, the red loud week still blocks
    assert _k(d.loc[:"2026-10-28"], WED_NEXT)["f_no_red_vol_week"] is False
    # after the next Friday close: that week (not another healthy red loud week) decides -> clear
    out = _k(d, FRI_NEXT)
    assert out["red_vol_week_date"] == "2026-10-30" and out["f_no_red_vol_week"] is True


def test_export_recheck_turns_pass_into_fail():
    hist = {"KNIFE": _hist(HEALTHY_RED_LOUD), "OK": _hist(RED_QUIET)}
    rows = [{"ticker": "KNIFE", "status": "PASS", "badges": ["pass"]}, {"ticker": "OK", "status": "PASS", "badges": ["pass"]}]
    blocked = XD.attach_red_vol_week(rows, "2026-10-24", hist=hist)
    assert blocked == ["KNIFE"]
    assert rows[0]["status"] == "FAIL" and "pass" not in rows[0]["badges"] and rows[0]["f_no_red_vol_week"] is False
    assert rows[1]["status"] == "PASS" and rows[1]["f_no_red_vol_week"] is True


def test_hot_list_never_ready_with_a_knife(tmp_path):
    import json
    from datetime import timedelta
    z = {"ok": True, "top": 100.0, "bottom": 99.0, "atr_w": 2.0, "score": 50, "price": 100.0, "last_week": "2026-10-26",
         "hammers": [{"w": "2026-10-26", "s": "H", "k": 1}],
         "trade": {"entry": 100.0, "sl": 98.0, "tp": 106.0, "rr": 3.0, "risk_pct": 2.0}}
    d, d0 = [], date(2026, 9, 7)
    for i, (lo, cl) in enumerate([(103, 104)] * 6 + [(99.5, 101)]):
        for j in range(5):
            dd = d0 + timedelta(days=7 * i + j)
            d.append([dd.isoformat(), cl, max(cl, lo) + 0.5, lo if j == 2 else min(cl, lo + 1), cl, 1000])
    (tmp_path / "candles").mkdir()
    (tmp_path / "expert_zones.json").write_text(json.dumps({"rule_version": "t", "tickers": {"A": z, "B": z}}))
    (tmp_path / "earnings.json").write_text("{}")
    for t in ("A", "B"):
        (tmp_path / "candles" / f"{t}.json").write_text(json.dumps({"t": t, "d": d}))
    mh = {"f_technical": True, "f_dollar_vol": True, "f_history": True, "current_price": 101.0}
    rows = [{**mh, "ticker": "A", "f_no_red_vol_week": False}, {**mh, "ticker": "B", "f_no_red_vol_week": True}]
    res = X.build(tmp_path, rows, {}, "2026-11-01")
    by = {x["t"]: x for x in res["items"]}
    assert by["B"]["tier"] == X.TIER_READY and by["B"]["knife"] is False
    assert by["A"]["tier"] == X.TIER_WAIT and by["A"]["knife"] is True
    assert by["A"]["reason_he"].startswith(X.KNIFE_HE)
