"""Expert watchlist (srs_app/expert_watch.py): criteria, readiness tiers, ranking."""
import json

from srs_app import expert_watch as X


def _z(top=100.0, bot=99.0, A=2.0, rr=3.0, entry=100.0, sl=98.0, risk_pct=2.0, score=50, hammers=()):
    return {"ok": True, "top": top, "bottom": bot, "atr_w": A, "score": score, "price": top, "last_week": "2026-10-26",
            "hammers": list(hammers), "trade": {"entry": entry, "sl": sl, "tp": entry + rr * (entry - sl), "rr": rr,
                                                "risk_pct": risk_pct}}


def _daily(closes_lows):
    """one weekly bar per (low, close) pair: Monday..Friday rows, Monday dates from 2026-09-07"""
    from datetime import date, timedelta
    out, d0 = [], date(2026, 9, 7)
    for i, (lo, cl) in enumerate(closes_lows):
        for j in range(5):
            d = d0 + timedelta(days=7 * i + j)
            out.append([d.isoformat(), cl, max(cl, lo) + 0.5, lo if j == 2 else min(cl, lo + 1), cl, 1000])
    return out


def _write(tmp, tickers, candles, earnings=None):
    (tmp / "candles").mkdir()
    (tmp / "expert_zones.json").write_text(json.dumps({"rule_version": "t", "tickers": tickers}))
    (tmp / "earnings.json").write_text(json.dumps(earnings or {}))
    for t, d in candles.items():
        (tmp / "candles" / f"{t}.json").write_text(json.dumps({"t": t, "d": d}))


def test_criteria_and_tiers(tmp_path):
    flat = _daily([(103, 104)] * 6 + [(99.5, 101)])              # last completed week dipped into the zone, closed above
    far = _daily([(110, 110)] * 7)
    tickers = {
        "READY": _z(),                                            # confirmation -> ready
        "WAIT": _z(),                                             # no signal (candles never touched)
        "FAR": _z(),                                              # 5 ATR above
        "LOWRR": _z(rr=1.5),
        "BIGRISK": _z(entry=1000, sl=900, top=1000, bot=995, risk_pct=10.0, A=20),   # $100 risk / share > $55
        "EARN": _z(),
        "BAD": {"ok": False, "reason": "broken"},
    }
    rows = [{"ticker": "READY", "current_price": 101.0}, {"ticker": "WAIT", "current_price": 101.0},
            {"ticker": "FAR", "current_price": 110.0}, {"ticker": "LOWRR", "current_price": 100.5},
            {"ticker": "BIGRISK", "current_price": 1001}, {"ticker": "EARN", "current_price": 100.5, "f_no_earnings_14d": False}]
    _write(tmp_path, tickers, {"READY": flat, "WAIT": _daily([(102.5, 103)] * 7), "FAR": far})
    res = X.build(tmp_path, rows, {}, "2026-11-01")
    got = {x["t"]: x for x in res["items"]}
    assert set(got) == {"READY", "WAIT"}
    assert got["READY"]["tier"] == X.TIER_READY and got["READY"]["rank"] == 1
    assert got["WAIT"]["tier"] == X.TIER_WAIT and got["WAIT"]["signals"] == []
    assert "R:R 3.0" in got["READY"]["reason_he"] and "סגירה שבועית מעל האזור" in got["READY"]["reason_he"]
    assert got["READY"]["shares"] == 27 and res["criteria"]["min_rr"] == X.WATCH_MIN_RR
    assert (tmp_path / "expert_watch.json").exists()


def test_signals_weekly_hammer_and_daily_reversal_only():
    z = _z(hammers=[{"w": "2026-10-26", "s": "H", "k": 1}])
    W = [{"low": 103, "close": 104, "high": 105}] * 3
    sg = X.signals(z, W, None)
    assert [s["k"] for s in sg] == ["hammerW"] and sg[0]["pts"] == 3
    rv = {"d": [[3, 4, 99.6, 100.4, 2.0]], "w": []}                # daily strong close touching the zone
    sg = X.signals(_z(), W, rv)
    assert [s["k"] for s in sg] == ["revD"] and sum(s["pts"] for s in sg) < X.READY_MIN_PTS   # daily alone = waiting
    rv = {"d": [], "w": [[5, 1, 99.6, 100.4, 2.0]]}                # weekly reversal too old (k >= READY_WEEKS)
    assert X.signals(_z(), W, rv) == []


def test_earnings_from_file_for_tickers_outside_the_report():
    from datetime import date
    assert not X._earn_ok_from_file({"n": "2026-11-05"}, date(2026, 11, 1), "2026-10-26")
    assert not X._earn_ok_from_file({"p": [{"d": "2026-10-28", "t": "bmo"}]}, date(2026, 11, 1), "2026-10-26")
    assert X._earn_ok_from_file({"n": "2026-12-01", "p": [{"d": "2026-10-16", "t": "amc"}]}, date(2026, 11, 1), "2026-10-26")
