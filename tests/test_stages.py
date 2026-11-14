"""Weinstein stage classifier (srs_app/stages.py, Eyal 2026-11-13) on synthetic weekly bars."""
import numpy as np
import pandas as pd

from srs_app.stages import buy_stop_price, classify, find_breakout, parse_earn, trading_days_until
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
    assert r["plan"]["stop"] < r["ma30"] and r["plan"]["entry"] == round(buy_stop_price(r["bo"]["level"]), 2)
    v[-2] = 1.2e6
    r2 = classify(bars(c, v, rng=0.01), bench(len(c)))
    assert r2["sub"] != "2A" and r2["bo"] and not r2["bo"]["vol_ok"]


def test_parse_earn_year():
    assert parse_earn("Nov 20/a", date(2026, 11, 13)) == "2026-11-20"
    assert parse_earn("Feb 03/b", date(2026, 11, 13)) == "2027-02-03"
    assert parse_earn("Oct 22/b", date(2026, 11, 13)) == "2026-10-22"
    assert trading_days_until("2026-11-20", date(2026, 11, 13)) == 5
    assert trading_days_until("2026-11-01", date(2026, 11, 13)) is None


# ---------------------------------------------------------------- Eyal 2026-11-14: overhead resistance / R:R / chase / earnings
from pathlib import Path
from srs_app.stages import RULES, buy_stop_price, earn_timing, earnings_live_week, overhead_scan, stage_path, trade_levels

DATA = Path(__file__).parent / "data"


def wk(t):
    return pd.read_csv(DATA / f"stages_{t}_weekly_20261113.csv.gz", index_col=0, parse_dates=True)


def test_kkr_overhead_rejects():
    """Eyal: KKR breakout 117.79, stop 97.15, overhead 144.11 -> R:R 1.28, stop 17.5% too wide -> skip."""
    w = wk("kkr")
    ov = overhead_scan(w, 117.79)
    assert not ov["open_sky"] and abs(ov["overhead"] - 144.11) < 0.5
    assert round((ov["overhead"] - 117.79) / (117.79 - 97.15), 2) in (1.27, 1.28)
    p = trade_levels(w, float(w["Close"].rolling(30).mean().iloc[-1]), 117.79, None, None)
    assert p["target_src"] == "overhead" and p["rr"] < RULES["min_rr"] and p["stop_wide"]


def test_wmt_open_sky():
    """Eyal: WMT breakout above 134.68 = all-time high, no overhead ('open sky') -> R:R 2.5 by construction."""
    w = wk("wmt")
    ov = overhead_scan(w, 134.68)
    assert ov["open_sky"] and ov["ath"]
    p = trade_levels(w, float(w["Close"].rolling(30).mean().iloc[-1]), 134.68, None, None)
    assert p["target_src"] == "open_sky" and p["rr"] == RULES["min_rr"]


def test_xers_not_chased():
    """Eyal: XERS $16.66, ~95% above the 30W SMA after the ~$10 breakout -> no entry."""
    r = classify(wk("xers"), None)
    assert r["stage"] == 2 and r["pct_ma"] > RULES["max_pct_above_ma"] and r["sub"] == "2-ext" and not r.get("plan")


def test_kkr_stage3_inside_range():
    """Inside its 2025-26 trading range the SMA crossings don't move KKR to stage 2 / 4."""
    w = wk("kkr")
    sp = stage_path(w, w["Close"].rolling(30).mean().values)
    assert sp["stage"] in (1, 3) and sp["floor"] < w["Close"].iloc[-1] < sp["ceil"]


def test_range_cross_stays_stage1():
    """A base after a decline whose close pokes above a rising SMA but stays under the base ceiling = still stage 1."""
    c = np.r_[np.linspace(80, 40, 60), 40 + 3 * np.sin(np.arange(40) / 2.5), np.linspace(40, 41.5, 6)]
    r = classify(bars(c, rng=0.01), bench(len(c)))
    assert r["stage"] == 1 and r["range"]["ceil"] > r["close"]


def test_buy_stop_and_earnings_week():
    assert abs(buy_stop_price(100.0) - 100.5) < 1e-9 and abs(buy_stop_price(5.0) - 5.05) < 1e-9
    assert earn_timing("Nov 19/b") == "b" and earn_timing("Nov 19/a") == "a" and earn_timing("Nov 19") is None
    sat = date(2026, 11, 14)
    assert earnings_live_week("2026-11-19", "b", sat)[0]          # Thursday of the live week
    assert earnings_live_week("2026-11-20", "b", sat)[0]          # Friday before the open
    assert not earnings_live_week("2026-11-20", "a", sat)[0]      # Friday after the close -> counts on Monday 11-23
    assert not earnings_live_week("2026-11-24", None, sat)[0]


def test_alert_text_only_when_candidates():
    from srs_app.stages import alert_text
    doc = {"week": "2026-11-13", "rules": RULES, "buy_stop_candidates": []}
    assert alert_text(doc) is None
    doc["buy_stop_candidates"] = [{"t": "ABC", "n": "Abc", "kind": "trigger", "sub": "1B", "close": 48.0, "level": 50.0, "buy_stop": 50.25,
                                   "stop": 46.0, "stop_pct": 8.5, "target": 60.88, "target_src": "open_sky", "open_sky": True, "rr": 2.5,
                                   "shares": 12, "pos_usd": 603.0, "vol_need": 2_000_000, "earn": "2027-01-20", "ex": "NYSE"}]
    txt = alert_text(doc)
    assert "ABC" in txt and "Buy-Stop $50.25" in txt and "R:R 1:2.5" in txt and "12 מניות" in txt and "2027-01-20" in txt and "2,000,000" in txt


def test_wide_stop_is_info_only():
    """Eyal 2026-11-14: don't disqualify for a wide stop, only flag it (SL% sort on the page)."""
    from srs_app.stages import entry_pass
    pre = [{"k": "price", "ok": True}]
    gates = [{"k": "rr", "ok": True}, {"k": "earn", "ok": True}]
    assert entry_pass(gates + [{"k": "stop", "ok": False, "info": True}], pre)
    assert not entry_pass(gates + [{"k": "chase", "ok": False}], pre)
    assert not entry_pass(gates, [{"k": "price", "ok": False}])


# ---------------------------------------------------------------- Eyal 2026-11-14: earnings window / estimate / post-earnings
import pandas as pd
from srs_app.stages import earn_check, earnings_info, post_earn_check, post_earn_gap, sessions_until


def test_earnings_10_session_window():
    sat = date(2026, 11, 14)
    assert sessions_until(date(2026, 11, 16), sat) == 1 and sessions_until(date(2026, 11, 27), sat) == 10
    ei = earnings_info("2026-11-26", "a", None, sat)                 # Thu after close -> trades Fri 11-27 = 10 sessions
    assert ei["eff"] == "2026-11-27" and ei["td"] == 10
    c = earn_check(ei)
    assert c["ok"] is False and c["he"].startswith("דוח בעוד 10 ימי מסחר – לא להציב Buy-Stop")
    assert earn_check(earnings_info("2026-11-30", "b", None, sat))["ok"] is True   # 11 sessions
    assert earn_check(earnings_info(None, None, None, sat))["ok"] is None


def test_past_finviz_date_is_estimated():
    sat = date(2026, 11, 14)
    ei = earnings_info("2026-08-25", "b", None, sat)                 # past -> +91d = 2026-11-24 (Tue), estimated
    assert ei["est"] and ei["next"] == "2026-11-24" and ei["td"] == 7 and ei["last"] == "2026-08-25"
    c = earn_check(ei)
    assert c["ok"] is False and "משוער" in c["he"]
    ei2 = earnings_info("2026-10-22", "a", None, sat)                # past -> 2027-01-21, out of the window
    assert ei2["est"] and ei2["next"] == "2027-01-21" and earn_check(ei2)["ok"] is True
    assert ei2["last_eff"] == "2026-10-23" and ei2["last_ago"] == 16
    ei3 = earnings_info("2026-10-22", "a", "2027-01-28", sat)        # a real cached future date wins over the estimate
    assert not ei3["est"] and ei3["next"] == "2027-01-28"


def _daily(closes, opens=None, vols=None, start="2026-10-01"):
    ix = pd.bdate_range(start, periods=len(closes))
    c = np.asarray(closes, float)
    o = np.asarray(opens if opens is not None else c, float)
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.005, "Low": np.minimum(o, c) * 0.995, "Close": c,
                         "Volume": np.asarray(vols if vols is not None else [1e6] * len(c), float)}, index=ix)


def test_post_earnings_gap_wait_then_hold():
    n = 25
    closes = [48.0] * 20 + [53.0, 52.5, 53.2, 52.8, 53.5]
    opens = [48.0] * 20 + [52.0, 53, 52.6, 53, 52.9]
    vols = [1e6] * 20 + [4e6, 2e6, 1.5e6, 1.2e6, 1e6]
    d = _daily(closes, opens, vols)
    gap_day = d.index[20].date().isoformat()
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    ei = {"last": gap_day, "last_eff": gap_day, "last_ago": 2}
    early = post_earn_gap(d.iloc[:22], w, gap_day, 50.0)             # gap day + 1 session -> wait
    assert early["gap"] and not early["hold"]
    c = post_earn_check(ei, early, 52.5, 50.0)
    assert c["ok"] is False and c["he"].startswith("גאפ אחרי דוח – לא לרדוף, להמתין להחזקה/בסיס קטן")
    held = post_earn_gap(d, w, gap_day, 50.0)                        # 4 sessions all closing above 50 -> mini-base
    assert held["hold"] and post_earn_check(dict(ei, last_ago=5), held, 53.5, 50.0)["ok"] is True
    assert n == len(d)


def test_post_earnings_back_under_resistance():
    d = _daily([48.0] * 20 + [48.5, 49.0, 49.2])
    day = d.index[20].date().isoformat()
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    pg = post_earn_gap(d, w, day, 50.0)
    assert not pg["gap"]
    c = post_earn_check({"last": day, "last_eff": day, "last_ago": 3}, pg, 49.2, 50.0)
    assert c["ok"] is True and c["he"].startswith("דוח עבר") and "להחזיר Buy-Stop" in c["he"]
    assert post_earn_check({"last": day, "last_eff": day, "last_ago": 9}, pg, 49.2, 50.0) is None


def test_stop_never_below_sma():
    """Eyal 2026-11-14 (final): default = 0.7% under the 30W SMA; a valid low ABOVE the SMA -> 0.7% under it; never under."""
    c = np.r_[np.full(30, 100.0), [104, 106, 103, 100, 104, 108, 110, 112, 111, 113]]
    w = bars(c, rng=0.01)
    w.iloc[33, w.columns.get_loc("Low")] = 98.0
    sw = 98.0                                   # the pullback low (pivot, never broken afterwards)
    p = trade_levels(w, 95.0, 115.0, 114.0, None)          # SMA 95 < low 98 -> use the low
    assert p["stop_basis"] == "low" and abs(p["stop"] - round(sw * 0.993, 2)) < 0.02 and p["swing_low"] == round(sw, 2)
    p2 = trade_levels(w, 101.0, 115.0, 114.0, None)        # low 98 under the SMA 101 -> SMA stop, the low is ignored
    assert p2["stop_basis"] == "ma" and abs(p2["stop"] - round(101 * 0.993, 2)) < 0.01 and p2["swing_low"] is None


def test_sector_status():
    """Eyal 2026-11-14: sector ETF not stage 4 + (clear stage 2 | late stage 1 awakening); RS is info only."""
    from srs_app.stages import sector_status
    e = lambda st, c, ma, sl, rs=-5.0: {"stage": st, "close": c, "ma30": ma, "slope_cls": sl, "rs": rs}
    assert sector_status(e(2, 110, 100, "up"))["he"] == "שלב 2 מובהק"
    s1 = sector_status(e(1, 105, 100, "flat", rs=-3.7))              # XLU-like: back above a flat SMA, negative RS
    assert s1["ok"] is True and s1["he"] == "סוף שלב 1 – התעוררות"
    assert sector_status(e(1, 95, 100, "flat"))["ok"] is False       # still under the SMA
    assert sector_status(e(1, 105, 100, "down"))["ok"] is False      # SMA still falling
    assert sector_status(e(4, 105, 100, "flat"))["ok"] is False      # stage 4 never
    assert sector_status(None)["ok"] is None
    assert sector_status(e(3, 110, 100, "up"))["ok"] is False        # stage 3 top: neither state


def test_research_needs_and_sql(tmp_path, monkeypatch):
    """Eyal 2026-11-14: candidates get a fundamental overview; refresh when older than 7 days; one line in Telegram."""
    import srs_app.stages as st
    monkeypatch.setattr(st, "RESEARCH_CACHE", tmp_path / "c.json")
    monkeypatch.setattr(st, "RESEARCH_SQL", tmp_path / "u.sql")
    doc = {"week": "2026-11-13", "rules": RULES, "buy_stop_candidates": [{"t": "DUK", "n": "Duke", "close": 129.16}, {"t": "ABC", "n": "Abc", "close": 10}]}
    f = tmp_path / "r.json"
    f.write_text('[{"ticker": "DUK", "summary_he": "תחום: חשמל O\'Brien", "data": {"short_he": "Buy · יעד $132", "as_of": "2026-11-14"}, "sources": ["https://finviz.com/quote.ashx?t=DUK"]}]')
    st.research_save(f)
    cache = st.research_cache()
    assert cache["DUK"]["data"]["scope"] == "stage_overview"
    sql = (tmp_path / "u.sql").read_text()
    assert "on conflict (ticker) do update" in sql and "O''Brien" in sql
    assert [x["t"] for x in st.needs_research(doc, cache, date(2026, 11, 20))] == ["ABC"]
    assert [x["t"] for x in st.needs_research(doc, cache, date(2026, 11, 22))] == ["DUK", "ABC"]   # 8 days old
    full = {**doc, "buy_stop_candidates": [{"t": "DUK", "n": "Duke", "kind": "trigger", "sub": "1B", "close": 129.16, "level": 132.18, "buy_stop": 132.84,
             "stop": 121.97, "stop_pct": 8.2, "target": 160.0, "target_src": "open_sky", "open_sky": True, "rr": 2.5, "shares": 5,
             "pos_usd": 664.0, "vol_need": None, "earn": "2027-02-04", "ex": "NYSE"}]}
    assert "📊 Buy · יעד $132" in st.alert_text(full, cache)
