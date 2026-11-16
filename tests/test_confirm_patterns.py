"""Confirmation candlestick patterns on the retest level (Eyal 2026-11-16, srs_app/confirm_patterns.py, v2 after NTRA).
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


@pytest.mark.parametrize("t,tf,code,end,k", [
    ("vtwo", "w", "inside3", "2026-10-26", 2),   # weekly three inside up, low 109.02 on 106.91-108.83 (tol min(0.1 ATR, 1%))
    ("hto", "w", "engulf", "2026-10-19", 3),     # weekly bullish engulfing, low 55.15 on 54.23-55.03
    ("gl", "d", "mdoji", "2026-11-09", 4),       # daily morning doji star, low 156.82 inside 155.61-157.63
    ("rbc", "d", "inside3", "2026-11-03", 8),    # daily three inside up, low 457.90 inside 457.40-465.80
])
def test_real_patterns_on_level(t, tf, code, end, k):
    c, lv = _level(t)
    hits = [p for p in lv[tf] if p["p"] == code and p["e"] == end]
    assert hits, (t, lv)
    assert hits[0]["k"] == k
    if tf == "w":
        assert hits[0]["entry"] is False                     # older than the last 2 completed weeks -> evidence, no entry
    else:
        assert "entry" not in hits[0]                        # daily = secondary confirmation, never the entry signal


def test_ntra_tiny_green_after_long_red_is_not_a_tweezer():
    """Eyal 2026-11-16: week of 02/11 red 418.41 -> 310.67 (low 304.00), week of 09/11 green 311.08 -> 319.09 (low
    304.65). Matching lows, but the green body (8) is short and closes far under the red body's midpoint (364.5)."""
    rows, (bot, top) = _fx("ntra")
    W = C.completed_weekly(rows, "2026-11-16")
    assert W[-1]["time"] == "2026-11-09" and W[-2]["low"] == 304.0
    assert not C.tweezer(W, len(W) - 1)
    c, lv = _level("ntra")
    assert not any(p["p"] == "tweezer" for p in c["w"]) and lv["w"] == [] and lv["entry"] is False
    # even a valid pattern with that low would be 16 points above the 279.29-288.04 zone: not on it
    assert not C.on_zone({"lo": 304.0, "c": 319.09, "a": 35.0}, top, bot)


@pytest.mark.parametrize("t,code,end", [
    ("dar", "engulf", "2026-11-09"),     # shape ok, low 49.78 is 1.8 under the 51.60-52.88 zone
    ("acmr", "hammerc", "2026-11-09"),   # shape ok, low 37.47 is 4.9 above the 29.33-32.54 zone (v1: 0.5 ATR let it in)
])
def test_off_level_patterns_rejected(t, code, end):
    c, lv = _level(t)
    assert any(p["p"] == code and p["e"] == end for p in c["w"])
    assert not any(p["p"] == code and p["e"] == end for p in lv["w"])


@pytest.mark.parametrize("t", ["ggll", "kex"])
def test_weak_tweezers_rejected(t):
    """v1 weekly tweezers of 2026-11-02 (GGLL) / 2026-11-09 (KEX): the green candle had no real buying."""
    c, lv = _level(t)
    assert not any(p["p"] == "tweezer" and p["k"] < 2 for p in c["w"])


def test_old_patterns_far_from_level_are_not_on_it():
    c, lv = _level("acmr")
    old = [p for p in c["w"] if p["e"] == "2026-09-21"]
    assert old and old[0]["p"] == "hammerc"
    assert not any(p["e"] == "2026-09-21" for p in lv["w"])  # low 62.78, far above the 29.33-32.54 zone


def _b(o, h, l, c, t="2026-01-05"):
    return {"time": t, "open": o, "high": h, "low": l, "close": c}


def _decline(n=20, start=120.0):
    """steady decline: red candles of body 1, range 2"""
    out, p = [], start
    for i in range(n):
        out.append(_b(p, p + 0.5, p - 1.5, p - 1.0, f"2026-01-{i + 1:02d}"))
        p -= 1.0
    return out


def test_engulfing_needs_a_prior_decline_and_a_real_body():
    B = _decline()
    p = B[-1]["close"]
    B += [_b(p + 0.2, p + 0.4, p - 2.0, p - 1.0, "2026-02-01"), _b(p - 1.5, p + 1.0, p - 1.8, p + 0.6, "2026-02-02")]
    assert C.engulf(B, len(B) - 1)
    assert [x["p"] for x in C.detect(B, 1)] == ["engulf"]
    small = B[:-2] + [_b(p + 0.2, p + 0.3, p - 0.5, p - 0.1, "2026-02-01"), _b(p - 0.15, p + 0.4, p - 0.5, p + 0.3, "2026-02-02")]
    assert not C.engulf(small, len(small) - 1)               # engulfs, but a short white body (<= BodyShort average)
    rally = [_b(100 + i, 101.5 + i, 99.5 + i, 101 + i, f"2026-01-{i + 1:02d}") for i in range(20)]
    q = rally[-1]["close"]
    rally += [_b(q + 0.2, q + 0.4, q - 0.4, q - 0.3, "2026-02-01"), _b(q - 0.5, q + 1.5, q - 0.6, q + 1.2, "2026-02-02")]
    assert C.engulf(rally, len(rally) - 1)
    assert C.detect(rally, 1) == []                          # same shape at the top of a rally: no pullback -> not counted


def test_tweezer_needs_real_buying():
    B = _decline()
    p = B[-1]["close"]
    red = _b(p + 0.2, p + 0.4, p - 4.0, p - 3.0, "2026-02-01")                # long red body 3.2, low p - 4
    tiny = B + [red, _b(p - 3.0, p - 1.0, p - 4.0, p - 2.6, "2026-02-02")]    # tiny green (0.4), under the midpoint
    assert not C.tweezer(tiny, len(tiny) - 1)
    real = B + [red, _b(p - 3.0, p + 0.0, p - 4.0, p - 0.8, "2026-02-02")]    # body 2.2, closes above midpoint p - 1.4
    assert C.tweezer(real, len(real) - 1)


def test_zone_gate_and_tolerance():
    p = {"p": "engulf", "k": 0, "s": "x", "e": "x", "lo": 99.8, "hi": 104, "c": 103, "a": 2.0}
    # tol = min(0.1 ATR = 0.2, 1% of the top = 1.01) = 0.2
    assert C.on_zone(p, 101, 100) and C.on_zone(dict(p, lo=101.2), 101, 100)
    assert not C.on_zone(dict(p, lo=99.7), 101, 100) and not C.on_zone(dict(p, lo=101.3), 101, 100)
    assert not C.on_zone(dict(p, lo=95.0, c=100.5), 101, 100)    # v1 loophole (closed back in the zone) removed
    q = dict(p, a=50.0)                                          # volatile: 1% of the top (1.01) < 0.1 ATR (5)
    assert C.on_zone(dict(q, lo=102.0), 101, 100) and not C.on_zone(dict(q, lo=102.1), 101, 100)
    assert C.CONFIRM["zone_tol_atr"] == 0.1 and C.CONFIRM["zone_tol_pct"] == 0.01


def test_entry_signal_needs_recent_and_unbroken():
    p = {"p": "engulf", "k": 1, "s": "x", "e": "x", "lo": 50.0, "hi": 55, "c": 54, "a": 2.0}
    assert C.is_entry(p, True, [52.0, 51.0])
    assert not C.is_entry(p, True, [49.9, 51.0])            # a later close under the pattern low cancels it
    assert not C.is_entry(dict(p, k=2), True, [52.0])       # older than the last 2 completed weeks
    assert not C.is_entry(dict(p, k=0), False, [])          # daily patterns are never the entry signal


def test_hammer_confirmation_closes_above_the_hammer_high():
    from srs_app import expert_zone as E
    assert E.hammer_shape(10, 10.1, 7, 9.8) == "H"          # the scanner's hammer definition is unchanged
    B = _decline()
    p = B[-1]["close"]
    B += [_b(p - 0.2, p, p - 3.0, p - 0.05, "2026-02-01"), _b(p, p + 1.2, p - 0.3, p + 1.0, "2026-02-02")]
    assert C.hammerc(B, len(B) - 1)                          # closes above the hammer's high (p)
    B[-1] = _b(p - 0.1, p + 0.3, p - 0.3, p - 0.02, "2026-02-02")  # green, above the hammer's close but not its high
    assert not C.hammerc(B, len(B) - 1)


def test_daily_only_never_makes_ready():
    z = {"top": 52.88, "bottom": 51.6, "atr_w": 3.0, "hammers": []}
    cf = {"w": [], "d": [{"p": "engulf", "k": 1, "s": "d", "e": "d", "lo": 51.7, "hi": 53, "c": 52.5, "a": 1.0}], "wc": [], "px": 52.5}
    sg = X.signals(z, [], None, cf)
    assert [s["k"] for s in sg] == ["confD"] and sum(s["pts"] for s in sg) < X.READY_MIN_PTS
    cf["w"] = [dict(cf["d"][0], k=0, a=3.0)]
    sg = X.signals(z, [], None, cf)
    assert "confW" in [s["k"] for s in sg] and sum(s["pts"] for s in sg) >= X.READY_MIN_PTS


def test_matches_talib():
    """TA-Lib port: morning star / doji star / piercing / three inside identical to TA-Lib on the fixtures; engulfing
    (+ Nison real white body) = a subset of TA-Lib's hits. Skipped without TA-Lib."""
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
                    mine = C.PATTERNS[k](B, i)
                    if k == "engulf":
                        assert not mine or ref[i] > 0, (f.name, k, B[i]["time"])
                    else:
                        assert mine == (ref[i] > 0), (f.name, k, B[i]["time"])
                    n += 1
    assert n > 1000
