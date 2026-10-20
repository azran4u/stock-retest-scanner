import numpy as np
import pandas as pd
import pytest

from srs.trend import TREND_DEFAULTS, enforce_spacing, find_pivots, trend


def weekly_from_path(points, steps=6):
    """Weekly bars whose closes follow straight segments between `points` (zig-zag)."""
    closes = []
    for a, b in zip(points, points[1:]):
        closes += list(np.linspace(a, b, steps + 1)[:-1])
    closes.append(points[-1])
    c = np.array(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    idx = pd.date_range("2023-01-06", periods=len(c), freq="W-FRI")
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) + 0.5, "Low": np.minimum(o, c) - 0.5,
                         "Close": c, "Volume": 1e6}, index=idx)


P = dict(pivot_k=2, min_sep_weeks=2, lookback_weeks=0, pullback="ignore", min_step_atr=0.0)


def test_find_pivots_basic_and_plateau():
    a = np.array([1, 2, 5, 2, 1, 3, 3, 1, 0])
    assert find_pivots(a, 2, "high") == [2, 5]          # plateau 3,3 -> first bar
    assert find_pivots(-a, 2, "low") == [2, 5]
    assert find_pivots(np.array([3, 2, 1, 2, 3, 2, 1, 2, 3.]), 2, "low") == [2, 6]


def test_last_k_bars_never_confirmed():
    a = np.array([1, 2, 3, 4, 5, 6, 9, 8])
    assert find_pivots(a, 2, "high") == []


def test_spacing_keeps_more_extreme():
    v = np.array([0, 5, 0, 7, 0, 0, 0, 0, 6, 0.])
    assert enforce_spacing([1, 3, 8], v, 3, "high") == [3, 8]
    assert enforce_spacing([1, 3, 8], v, 1, "high") == [1, 3, 8]


def test_clean_uptrend():
    w = weekly_from_path([10, 20, 15, 25, 20, 30, 26])
    r = trend(w, **P)
    assert r["trend"] == "up", r["reason"]
    assert [s["price"] for s in r["swing_highs"]][-2:] == [25.5, 30.5]


def test_clean_downtrend():
    w = weekly_from_path([30, 20, 25, 15, 20, 10, 14])
    r = trend(w, **P)
    assert r["trend"] == "down", r["reason"]


def test_range_is_none():
    w = weekly_from_path([10, 20, 10, 20, 10, 20, 10, 20])
    assert trend(w, **P)["trend"] == "none"


def test_mixed_higher_highs_lower_lows_is_none():
    w = weekly_from_path([20, 25, 15, 30, 10, 35, 30])
    assert trend(w, **P)["trend"] == "none"                       # lows 15 -> 10 before the 35 high
    # "judge" treats the current pullback low (~29.5) as the newest swing low -> higher low vs 10
    assert trend(w, **{**P, "pullback": "judge"})["trend"] == "up"


def test_unconfirmed_new_high_counts():
    # range 12..20 then a breakout to 26.5 in the last 2 bars (not a confirmed pivot with k=2)
    w = weekly_from_path([12, 20, 14, 20, 16, 26], steps=6)
    nxt = w.index[-1] + pd.Timedelta(weeks=1)
    w.loc[nxt] = {"Open": 26.0, "High": 26.2, "Low": 24.5, "Close": 25.0, "Volume": 1e6}
    r = trend(w, **P)
    assert r["swing_highs"][-1]["confirmed"] is False
    assert r["trend"] == "up", r["reason"]
    assert trend(w, **{**P, "provisional": False})["trend"] == "none"


def test_pullback_modes():
    # HH/HL, then the current pullback undercuts the last higher low (24 < 26)
    w = weekly_from_path([10, 20, 15, 25, 20, 30, 18], steps=6)
    assert trend(w, **{**P, "pullback": "judge", "break_close": False})["trend"] == "none"
    assert trend(w, **{**P, "pullback": "ignore", "break_close": False})["trend"] == "up"
    assert trend(w, **{**P, "pullback": "ignore", "break_close": True})["trend"] == "none"


def test_min_step_atr():
    w = weekly_from_path([10, 20, 15, 20.6, 15.6, 21.2, 18])
    assert trend(w, **P)["trend"] == "up"
    assert trend(w, **{**P, "min_step_atr": 1.0})["trend"] == "none"


def test_deterministic_and_params_echoed():
    w = weekly_from_path([10, 20, 15, 25, 20, 30, 26])
    assert trend(w, **P) == trend(w, **P)
    assert set(trend(w)["params"]) == set(TREND_DEFAULTS)


def test_bad_params():
    w = weekly_from_path([10, 20, 15, 25])
    with pytest.raises(TypeError):
        trend(w, nope=1)
    with pytest.raises(ValueError):
        trend(w, price="mid")


def test_too_short():
    assert trend(weekly_from_path([10, 11]), **P)["trend"] == "none"
