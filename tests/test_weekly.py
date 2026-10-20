import numpy as np
import pandas as pd
import pytest

from srs.weekly import last_complete_week_end, to_weekly, week_end


def daily(start, n, base=10.0):
    idx = pd.bdate_range(start, periods=n)
    i = np.arange(n, dtype=float)
    return pd.DataFrame({"Open": base + i, "High": base + i + 2, "Low": base + i - 1,
                         "Close": base + i + 1, "Volume": 100 + i}, index=idx)


def test_two_full_weeks_aggregation():
    d = daily("2026-10-05", 10)  # Mon 10-05 .. Fri 10-16
    w = to_weekly(d)
    assert list(w.index.strftime("%Y-%m-%d")) == ["2026-10-09", "2026-10-16"]
    a = w.iloc[0]
    assert a.Open == 10 and a.Close == 15 and a.High == 16 and a.Low == 9 and a.Volume == sum(100 + i for i in range(5))
    b = w.iloc[1]
    assert b.Open == 15 and b.Close == 20 and b.High == 21 and b.Low == 14


def test_holiday_gap_and_partial_week():
    d = daily("2026-10-05", 8).drop(pd.Timestamp("2026-10-07"))  # Wed missing; ends Wed 10-14
    w = to_weekly(d)
    assert len(w) == 2 and w.index[-1] == pd.Timestamp("2026-10-16")
    assert to_weekly(d, drop_incomplete=True).index[-1] == pd.Timestamp("2026-10-09")


def test_asof_cut_and_drop_incomplete():
    d = daily("2026-10-05", 15)  # through Fri 10-23
    w = to_weekly(d, asof="2026-10-14")
    assert w.index[-1] == pd.Timestamp("2026-10-16") and w.iloc[-1].Close == d.loc["2026-10-14", "Close"]
    assert to_weekly(d, asof="2026-10-14", drop_incomplete=True).index[-1] == pd.Timestamp("2026-10-09")
    assert to_weekly(d, asof="2026-10-16", drop_incomplete=True).index[-1] == pd.Timestamp("2026-10-16")
    # a Monday asof: last complete week is the Friday before
    assert to_weekly(d, asof="2026-10-19", drop_incomplete=True).index[-1] == pd.Timestamp("2026-10-16")


def test_tz_aware_lowercase_columns_and_duplicates():
    d = daily("2026-10-05", 5)
    d.columns = [c.lower() for c in d.columns]
    d.index = d.index.tz_localize("America/New_York")
    d = pd.concat([d, d.iloc[[-1]]])
    w = to_weekly(d)
    assert len(w) == 1 and w.iloc[0].Volume == sum(100 + i for i in range(5))


def test_matches_scanner_definition():
    """Same rule as stock_screen.to_weekly (re-implemented inline so the test needs no /workspace)."""
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=400)
    c = 50 + rng.normal(0, 1, 400).cumsum()
    d = pd.DataFrame({"Open": c + rng.normal(0, .3, 400), "Close": c,
                      "Volume": rng.integers(1e5, 1e6, 400)}, index=idx)
    d["High"] = d[["Open", "Close"]].max(axis=1) + .5
    d["Low"] = d[["Open", "Close"]].min(axis=1) - .5
    ref = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                   "Volume": "sum"}).dropna()
    pd.testing.assert_frame_equal(to_weekly(d).astype(float), ref.astype(float), check_freq=False, check_names=False)


def test_week_helpers():
    assert week_end("2026-10-14") == pd.Timestamp("2026-10-16")
    assert week_end("2026-10-16") == pd.Timestamp("2026-10-16")
    assert last_complete_week_end("2026-10-20") == pd.Timestamp("2026-10-16")
    assert last_complete_week_end("2026-10-16") == pd.Timestamp("2026-10-16")


def test_missing_column_raises():
    with pytest.raises(ValueError):
        to_weekly(daily("2026-10-05", 5).drop(columns="Volume"))
