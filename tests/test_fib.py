"""Fibonacci anchor (weekly ZigZag, 3 x Wilder ATR(14)) + confluence + weekly-sampled daily SMAs (srs_app/fib.py)."""
from datetime import date, timedelta

import pytest

from srs_app.fib import (FIB_PRICE_TOL_ATR, fib_anchor, fib_confluence, fib_levels, sma_weekly, weekly_bars,
                         wilder_atr_series, zigzag_pivots)


def _daily_from_weekly(path, start=date(2024, 1, 1)):
    """One flat daily bar per weekday per week with the week's (low, high); close = midpoint (Mon low, Wed high)."""
    rows, d = [], start
    for lo, hi in path:
        for k in range(5):
            day = d + timedelta(days=k)
            c = (lo + hi) / 2
            h = hi if k == 2 else c + 0.1
            l = lo if k == 0 else c - 0.1
            rows.append([day.isoformat(), c, h, l, c, 1000])
        d += timedelta(days=7)
    return rows


def test_weekly_bars_keep_dates_of_extremes():
    rows = _daily_from_weekly([(10, 12), (11, 13)])
    w = weekly_bars(rows)
    assert len(w) == 2 and w[0]["time"] == "2024-01-01" and w[1]["time"] == "2024-01-08"
    assert w[0]["low"] == 10 and w[0]["lo_date"] == "2024-01-01" and w[0]["high"] == 12 and w[0]["hi_date"] == "2024-01-03"


def test_atr_matches_app_recursion():
    bars = [{"high": 10 + i % 3, "low": 9 + i % 2, "close": 9.5 + (i % 4) / 2} for i in range(30)]
    a = wilder_atr_series(bars, 14)
    assert a[13] is None and a[14] is not None
    x = 0.0
    for i in range(1, 30):
        tr = max(bars[i]["high"] - bars[i]["low"], abs(bars[i]["high"] - bars[i - 1]["close"]), abs(bars[i]["low"] - bars[i - 1]["close"]))
        x = x + tr / 14 if i <= 14 else (x * 13 + tr) / 14
    assert a[-1] == pytest.approx(x)


def _path():
    # 20 quiet weeks (ATR ~2), rally to 140 (swing high), drop to 100 (swing low, confirmed by the rise), rally to 150, pullback to 130
    p = [(99, 101)] * 20
    p += [(100 + 4 * i, 102 + 4 * i) for i in range(10)]          # up to 138-140
    p += [(136 - 4 * i, 138 - 4 * i) for i in range(9)]           # down to 104-106
    p += [(100, 103)]                                              # swing low 100
    p += [(104 + 5 * i, 107 + 5 * i) for i in range(9)]           # up to 144-147
    p += [(146, 150)]                                              # swing high 150
    p += [(140, 145), (133, 138), (130, 134)]                      # pullback (not a new low)
    return p


def test_zigzag_pivots_and_anchor():
    rows = _daily_from_weekly(_path())
    bars = weekly_bars(rows)
    piv = zigzag_pivots(bars)
    kinds = [p["kind"] for p in piv]
    assert "H" in kinds and kinds[-1] in ("L", "H")
    f = fib_anchor(rows)
    assert f["low"] == 100 and f["high"] == 150
    assert f["low_date"] < f["high_date"]
    lv = f["levels"]
    assert lv["0.0"] == 150 and lv["1.0"] == 100 and lv["0.5"] == 125 and lv["0.382"] == pytest.approx(130.9) and lv["0.618"] == pytest.approx(119.1)


def test_no_confirmed_low_no_fib():
    rows = _daily_from_weekly([(99, 101)] * 40)  # sideways: never a 3 ATR move
    assert fib_anchor(rows) is None


def test_new_lower_low_needs_confirmation():
    # after the 150 high price falls to 90 (below the old low) and has not risen 3 ATR yet -> the anchor stays 100 -> 150
    p = _path() + [(120 - 10 * i, 124 - 10 * i) for i in range(4)]
    f = fib_anchor(_daily_from_weekly(p))
    assert f["low"] == 100 and f["high"] == 150
    # ... then a strong rise from 90 confirms 90 as the new swing low -> anchor = 90 -> the new high
    p += [(95 + 6 * i, 99 + 6 * i) for i in range(8)]
    f2 = fib_anchor(_daily_from_weekly(p))
    assert f2["low"] == 90 and f2["high"] == 99 + 6 * 7


def test_confluence_price_and_zone():
    c = fib_confluence(100, 150, 4.0, price=125.5)
    assert c["price_level"] == 0.5
    c = fib_confluence(100, 150, 4.0, price=125 + FIB_PRICE_TOL_ATR * 4 + 0.01)
    assert c["price_level"] is None
    c = fib_confluence(100, 150, 4.0, price=131.0, zone_top=127, zone_bottom=124)   # 130.9 -> 0.382; zone holds 125
    assert c["price_level"] == 0.382 and c["zone_levels"] == [0.5]
    assert fib_confluence(100, 150, 4.0, zone_top=118.6, zone_bottom=118.0)["zone_levels"] == []
    assert fib_confluence(100, 150, 4.0, zone_top=118.8, zone_bottom=118.0)["zone_levels"] == [0.618]       # 119.1 - 118.8 = 0.3 <= 0.4
    assert fib_confluence(100, 150, None, price=125)["price_level"] is None
    assert fib_levels(100, 150)["0.618"] == pytest.approx(119.1)


def test_sma_weekly_sampled_at_last_trading_day():
    rows = [[(date(2024, 1, 1) + timedelta(days=i)).isoformat(), 1, 1, 1, float(i), 0] for i in range(400)
            if (date(2024, 1, 1) + timedelta(days=i)).weekday() < 5]
    sm = sma_weekly(rows, (50, 200))
    w = weekly_bars(rows)
    assert len(sm[50]) == len(w)
    closes = [r[4] for r in rows]
    assert sm[50][-1] == pytest.approx(sum(closes[-50:]) / 50)
    assert sm[200][0] is None
    # a mid week: value = SMA at that week's Friday
    fri = max(i for i, r in enumerate(rows) if r[0] <= w[45]["last"])
    assert sm[50][45] == pytest.approx(sum(closes[fri - 49:fri + 1]) / 50)
