"""Weinstein stage classifier (srs_app/stages.py, Eyal 2026-11-13) on synthetic weekly bars."""
import numpy as np
import pandas as pd

from srs_app.stages import classify, find_breakout, parse_earn, trading_days_until
from datetime import date


def bars(closes, vols=None, rng=0.02):
    c = np.asarray(closes, float)
    idx = pd.date_range("2023-01-06", periods=len(c), freq="W-FRI")
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * (1 + rng), "Low": np.minimum(o, c) * (1 - rng),
                         "Close": c, "Volume": vols if vols is not None else np.full(len(c), 1e6)}, index=idx)


def bench(n):
    return pd.Series(np.full(n, 100.0), index=pd.date_range("2023-01-06", periods=n, freq="W-FRI"))


def test_stage2_uptrend():
    w = bars(np.linspace(20, 60, 120) * (1 + 0.03 * np.sin(np.arange(120) / 3)))
    r = classify(w, bench(120))
    assert r["stage"] == 2 and r["slope_cls"] == "up"


def test_stage4_downtrend():
    w = bars(np.linspace(60, 20, 120) * (1 + 0.03 * np.sin(np.arange(120) / 3)))
    r = classify(w, bench(120))
    assert r["stage"] == 4


def test_stage1_base_after_decline():
    c = np.r_[np.linspace(80, 40, 60), 40 + 1 * np.sin(np.arange(50) / 2)]
    r = classify(bars(c), bench(len(c)))
    assert r["stage"] == 1 and r["sub"] == "1B" and r["base"]["top"] > 40


def test_stage3_top_after_advance():
    c = np.r_[np.linspace(20, 60, 60), 60 + 1 * np.sin(np.arange(50) / 2)]
    r = classify(bars(c), bench(len(c)))
    assert r["stage"] == 3


def test_breakout_2a_needs_volume():
    base = 40 + 1.5 * np.sin(np.arange(40) / 2)
    c = np.r_[np.linspace(80, 40, 50), base, 46, 46.5]
    v = np.full(len(c), 1e6); v[-2] = 3e6
    r = classify(bars(c, v, rng=0.01), bench(len(c)))
    assert r["sub"] == "2A" and r["stage"] == 2 and r["bo"]["vol_ok"] and r["bo"]["weeks_ago"] == 1
    assert r["plan"]["stop"] < r["ma30"] and r["plan"]["entry"] == 46.5
    v[-2] = 1.2e6
    r2 = classify(bars(c, v, rng=0.01), bench(len(c)))
    assert r2["sub"] != "2A" and r2["bo"] and not r2["bo"]["vol_ok"]


def test_parse_earn_year():
    assert parse_earn("Nov 20/a", date(2026, 11, 13)) == "2026-11-20"
    assert parse_earn("Feb 03/b", date(2026, 11, 13)) == "2027-02-03"
    assert parse_earn("Oct 22/b", date(2026, 11, 13)) == "2026-10-22"
    assert trading_days_until("2026-11-20", date(2026, 11, 13)) == 5
    assert trading_days_until("2026-11-01", date(2026, 11, 13)) is None
