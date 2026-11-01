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
    assert X.earn_block({"n": "2026-11-05"}, {}, date(2026, 11, 1), "2026-10-26")
    assert X.earn_block({"p": [{"d": "2026-10-28", "t": "bmo"}]}, {}, date(2026, 11, 1), "2026-10-26")
    assert X.earn_block({"n": "2026-12-01", "p": [{"d": "2026-10-16", "t": "amc"}]}, {}, date(2026, 11, 1), "2026-10-26") is None


def test_earnings_gate_live_irm_rok_mufg(tmp_path):
    """Regression 2026-11-01: IRM / ROK (report 11/05, rows WITHOUT f_no_earnings_14d) and MUFG (11/13 = 12 days;
    the report row said f_no_earnings_14d=True as of 10/30) were in the watchlist. earnings.json is flat {T: {...}}.
    SLG reported 10/21 amc (reaction 10/22, week 10/19) -> last completed week 10/26 is clean -> stays."""
    flat = _daily([(103, 104)] * 6 + [(99.5, 101)])
    earn = {
        "IRM": {"p": [{"d": "2026-08-05", "t": "bmo"}], "n": "2026-11-05", "ne": True, "nt": "bmo"},
        "ROK": {"p": [{"d": "2026-08-03", "t": "amc"}], "n": "2026-11-05", "ne": True, "nt": "bmo"},
        "MUFG": {"p": [{"d": "2026-08-03", "t": "bmo"}], "n": "2026-11-13", "ne": False, "nt": None},
        "SLG": {"p": [{"d": "2026-07-21", "t": "amc"}, {"d": "2026-10-21", "t": "amc"}], "n": "2027-01-27", "ne": True},
        "WKAMC": {"p": [{"d": "2026-10-23", "t": "amc"}], "n": "2027-01-20"},    # Fri amc -> reacts Mon 10/26 (last week)
        "WKBMO": {"p": [{"d": "2026-10-28", "t": "bmo"}], "n": "2027-01-20"},
        "OFFROW": {"n": "2026-11-04"},                                           # no report row: file only
    }
    names = ["IRM", "ROK", "MUFG", "SLG", "WKAMC", "WKBMO", "OFFROW", "CLEAN"]
    rows = [{"ticker": "IRM", "current_price": 101.0, "f_after_earnings_week": True},
            {"ticker": "ROK", "current_price": 101.0, "f_after_earnings_week": True},
            {"ticker": "MUFG", "current_price": 101.0, "earnings_date": "2026-11-13", "f_no_earnings_14d": True,
             "f_after_earnings_week": True},
            {"ticker": "SLG", "current_price": 101.0, "f_after_earnings_week": True},
            {"ticker": "WKAMC", "current_price": 101.0}, {"ticker": "WKBMO", "current_price": 101.0},
            {"ticker": "CLEAN", "current_price": 101.0, "earnings_date": "2026-11-15"}]   # 14 days -> clear
    _write(tmp_path, {t: _z() for t in names}, {t: flat for t in names}, earn)
    res = X.build(tmp_path, rows, {}, "2026-11-01")
    assert {x["t"] for x in res["items"]} == {"SLG", "CLEAN"}
    ex = res["earn_excluded"]
    assert set(ex) == {"IRM", "ROK", "MUFG", "WKAMC", "WKBMO", "OFFROW"}
    assert "4 ימים" in ex["IRM"] and "12 ימים" in ex["MUFG"]


def test_reason_line_is_short(tmp_path):
    flat = _daily([(103, 104)] * 6 + [(99.5, 101)])
    _write(tmp_path, {"A": _z(hammers=[{"w": "2026-10-26", "s": "H", "k": 1}]), "B": _z()},
           {"A": flat, "B": _daily([(102.5, 103)] * 7)})
    rv = {"A": {"d": [[1, 1, 99.8, 100.5, 2.0]], "w": []}}
    res = X.build(tmp_path, [{"ticker": "A", "current_price": 101.0}, {"ticker": "B", "current_price": 101.0}], rv, "2026-11-01")
    got = {x["t"]: x["reason_he"] for x in res["items"]}
    assert got["A"] == "סגירה שבועית מעל האזור אחרי נגיעה · R:R 3.0 · 0.5 ATR מעל"
    assert got["B"].startswith("ממתינה לסימן היפוך · R:R 3.0")
    assert got["A"].count("·") == 2
