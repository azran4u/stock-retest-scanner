"""Confirmation candlestick patterns on the retest level (Eyal 2026-11-16, srs_app/confirm_patterns.py).
Real candles (app/data/candles as of 2026-11-13, last 220 sessions) + synthetic edge cases + a TA-Lib cross-check."""
import json
from pathlib import Path

import pytest

from srs_app import confirm_patterns as C
from srs_app import expert_watch as X

D = Path(__file__).parent / "data"


def _fx(t):
    j = json.loads((D / f"confirm_{t}_daily_20261113.json").read_text())
    return j["d"], j["zone"]


def _level(t):
    rows, (bot, top) = _fx(t)
    c = C.of_rows(rows, "2026-11-16")
    return c, C.on_level(c, top, bot)


@pytest.mark.parametrize("t,code,week,k", [
    ("dar", "engulf", "2026-11-09", 0),     # red week then a green week whose body engulfs it, low 49.78 on 51.60-52.88
    ("acmr", "hammerc", "2026-11-09", 0),   # hammer week of 11-02 confirmed by a green week closing above its close
    ("ggll", "tweezer", "2026-11-02", 1),   # red + green week with matching lows 62.13 at 63.45-66.83
    ("kex", "tweezer", "2026-11-09", 0),    # matching lows 118.0 at 119.00-122.50
])
def test_real_weekly_patterns_on_level(t, code, week, k):
    c, lv = _level(t)
    hits = [p for p in lv["w"] if p["p"] == code and p["e"] == week]
    assert hits, (t, lv["w"])
    assert hits[0]["k"] == k
    assert hits[0]["entry"] is True and lv["entry"] is True


def test_real_daily_secondary():
    c, lv = _level("dar")
    assert any(p["p"] == "engulf" and p["e"] == "2026-11-09" for p in lv["d"])
    assert all("entry" not in p for p in lv["d"])          # daily = secondary confirmation, never the entry signal


def test_old_patterns_far_from_level_are_not_on_it():
    c, lv = _level("acmr")
    old = [p for p in c["w"] if p["e"] == "2026-09-21"]
    assert old and old[0]["p"] == "hammerc"
    assert not any(p["e"] == "2026-09-21" for p in lv["w"])  # low 62.78, far above the 29.33-32.54 zone


def _b(o, h, l, c, t="2026-01-05"):
    return {"time": t, "open": o, "high": h, "low": l, "close": c}


def _decline(n=20, start=120.0, step=1.0):
    """steady decline: red candles of body 1, range 2"""
    out = []
    p = start
    for i in range(n):
        out.append(_b(p, p + 0.5, p - 1.5, p - 1.0, f"2026-01-{i + 1:02d}"))
        p -= 1.0
    return out


def test_engulfing_needs_a_prior_decline():
    B = _decline()
    p = B[-1]["close"]
    B += [_b(p + 0.2, p + 0.4, p - 2.0, p - 1.0, "2026-02-01"), _b(p - 1.5, p + 1.0, p - 1.8, p + 0.6, "2026-02-02")]
    assert C.engulf(B, len(B) - 1)
    assert [x["p"] for x in C.detect(B, 1)] == ["engulf"]
    rally = [_b(100 + i, 101.5 + i, 99.5 + i, 101 + i, f"2026-01-{i + 1:02d}") for i in range(20)]
    q = rally[-1]["close"]
    rally += [_b(q + 0.2, q + 0.4, q - 0.4, q - 0.3, "2026-02-01"), _b(q - 0.5, q + 1.0, q - 0.6, q + 0.5, "2026-02-02")]
    assert C.engulf(rally, len(rally) - 1)
    assert C.detect(rally, 1) == []                         # same shape at the top of a rally: no pullback -> not counted


def test_zone_gate_and_tolerance():
    p = {"p": "engulf", "k": 0, "s": "x", "e": "x", "lo": 99.0, "hi": 104, "c": 103, "a": 2.0}
    assert C.on_zone(p, 101, 100)                           # low 1 under the bottom = 0.5 ATR -> touches
    assert not C.on_zone(dict(p, lo=98.9, c=99.5), 101, 100)  # deeper and closed under the zone
    assert C.on_zone(dict(p, lo=95.0, c=100.5), 101, 100)   # deep wick, closed back inside
    assert C.on_zone(dict(p, lo=102.0), 101, 100) and not C.on_zone(dict(p, lo=102.1), 101, 100)
    assert C.CONFIRM["zone_tol_atr"] == 0.5


def test_entry_signal_needs_recent_and_unbroken():
    p = {"p": "engulf", "k": 1, "s": "x", "e": "x", "lo": 50.0, "hi": 55, "c": 54, "a": 2.0}
    assert C.is_entry(p, True, [52.0, 51.0])
    assert not C.is_entry(p, True, [49.9, 51.0])            # a later close under the pattern low cancels it
    assert not C.is_entry(dict(p, k=2), True, [52.0])       # older than the last 2 completed weeks
    assert not C.is_entry(dict(p, k=0), False, [])          # daily patterns are never the entry signal


def test_hammer_definition_unchanged():
    from srs_app import expert_zone as E
    assert C.hammerc.__module__ == C.__name__ and E.hammer_shape(10, 10.1, 7, 9.8) == "H"
    B = _decline()
    p = B[-1]["close"]
    B += [_b(p - 0.2, p, p - 3.0, p - 0.05, "2026-02-01"), _b(p, p + 1.2, p - 0.3, p + 1.0, "2026-02-02")]
    assert C.hammerc(B, len(B) - 1)
    B[-1] = _b(p, p + 0.3, p - 0.3, p - 0.1, "2026-02-02")  # next candle red / not above the hammer's close
    assert not C.hammerc(B, len(B) - 1)


def test_daily_only_never_makes_ready():
    z = {"top": 52.88, "bottom": 51.6, "atr_w": 3.0, "hammers": []}
    cf = {"w": [], "d": [{"p": "engulf", "k": 1, "s": "d", "e": "d", "lo": 51.0, "hi": 53, "c": 52.5, "a": 1.0}], "wc": [], "px": 52.5}
    sg = X.signals(z, [], None, cf)
    assert [s["k"] for s in sg] == ["confD"] and sum(s["pts"] for s in sg) < X.READY_MIN_PTS
    cf["w"] = [dict(cf["d"][0], k=0, a=3.0)]
    sg = X.signals(z, [], None, cf)
    assert "confW" in [s["k"] for s in sg] and sum(s["pts"] for s in sg) >= X.READY_MIN_PTS


def test_matches_talib():
    """Port of TA-Lib's candle settings: bullish hits identical to TA-Lib on the fixtures (skipped without TA-Lib)."""
    talib = pytest.importorskip("talib")
    np = pytest.importorskip("numpy")
    fn = {"engulf": talib.CDLENGULFING, "mstar": lambda *a: talib.CDLMORNINGSTAR(*a, penetration=0.3),
          "mdoji": lambda *a: talib.CDLMORNINGDOJISTAR(*a, penetration=0.3), "pierce": talib.CDLPIERCING, "inside3": talib.CDL3INSIDE}
    n = 0
    for f in D.glob("confirm_*_daily_20261113.json"):
        rows = json.loads(f.read_text())["d"]
        for B in (C.completed_weekly(rows), [C._bar(r) for r in rows]):
            arr = [np.array([b[k] for b in B], float) for k in ("open", "high", "low", "close")]
            for k, g in fn.items():
                ref = g(*arr)
                for i in range(12, len(B)):
                    assert C.PATTERNS[k](B, i) == (ref[i] > 0), (f.name, k, B[i]["time"])
                    n += 1
    assert n > 1000
