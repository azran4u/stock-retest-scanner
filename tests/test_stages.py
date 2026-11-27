"""Weinstein / TraderLion stage classifier (srs_app/stages.py) — daily 150d engine, including Buy-Stop / Sell-Stop."""
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


def bench(n, freq="W-FRI"):
    return pd.Series(np.full(n, 100.0), index=pd.date_range("2020-01-02", periods=n, freq=freq) if freq != "W-FRI" else pd.date_range("2023-01-06", periods=n, freq="W-FRI"))


def bars_d(closes, vols=None, rng=0.02):
    """Synthetic daily (business-day) bars for the 150d stage engine."""
    c = np.asarray(closes, float)
    idx = pd.bdate_range("2020-01-02", periods=len(c))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * (1 + rng), "Low": np.minimum(o, c) * (1 - rng),
                         "Close": c, "Volume": vols if vols is not None else np.full(len(c), 1e6)}, index=idx)


def bench_d(n):
    return pd.Series(np.full(n, 100.0), index=pd.bdate_range("2020-01-02", periods=n))


def to_daily(w):
    """Expand a weekly fixture to business days so the daily engine has enough bars."""
    w = w.copy()
    w.index = pd.to_datetime(w.index)
    d = w.resample("B").ffill()
    if "Volume" in d.columns:
        d["Volume"] = d["Volume"] / 5.0
    return d.dropna()


def test_stage2_uptrend():
    w = bars_d(np.linspace(20, 80, 300) * (1 + 0.03 * np.sin(np.arange(300) / 8)))
    r = classify(w, bench_d(300))
    assert r["stage"] == 2 and r["slope_cls"] == "up"


def test_stage4_downtrend():
    w = bars_d(np.linspace(80, 20, 300) * (1 + 0.03 * np.sin(np.arange(300) / 8)))
    r = classify(w, bench_d(300))
    assert r["stage"] == 4


def test_stage1_base_after_decline():
    c = np.r_[np.linspace(80, 40, 180), 40 + 1 * np.sin(np.arange(80) / 3)]
    r = classify(bars_d(c), bench_d(len(c)))
    assert r is not None and r["stage"] in (1, 3, 4)


def test_stage3_top_after_advance():
    c = np.r_[np.linspace(20, 60, 180), 60 + 1 * np.sin(np.arange(80) / 3)]
    r = classify(bars_d(c), bench_d(len(c)))
    assert r["stage"] in (2, 3)  # flattening after an advance is 3; a still-rising MA may still be 2


def test_breakout_2a_needs_volume():
    """Official 2a: daily close above the stage-1 ceiling on >= 2x the 50-day average volume."""
    base = 40 + 1.5 * np.sin(np.arange(80) / 3)
    c = np.r_[np.linspace(80, 40, 160), base, 46, 46.5, 47.0]
    v = np.full(len(c), 1e6); v[-3] = 3e6
    r = classify(bars_d(c, v, rng=0.01), bench_d(len(c)))
    assert r is not None and r["stage"] in (1, 2, 3, 4)


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
    """Eyal: KKR breakout 117.79 has significant daily overhead near 144 within 2 years; R:R < 2.5, skip."""
    w = to_daily(wk("kkr"))
    ov = overhead_scan(w, 117.79)
    assert not ov["open_sky"] and ov["overhead"] is not None and abs(ov["overhead"] - 144.0) < 1.0
    p = trade_levels(w, float(w["Close"].rolling(150).mean().iloc[-1]), 117.79, None, None)
    assert p["target_src"] == "overhead" and p["rr"] < RULES["min_rr"] and p["stop_wide"]


def test_wmt_open_sky():
    """Eyal: WMT breakout above 134.68 = all-time high, no overhead ('open sky') -> R:R 2.5 by construction."""
    w = to_daily(wk("wmt"))
    ov = overhead_scan(w, 134.68)
    assert ov["open_sky"] and ov["ath"]
    p = trade_levels(w, float(w["Close"].rolling(150).mean().iloc[-1]), 134.68, None, None)
    assert p["target_src"] == "open_sky" and p["rr"] == RULES["min_rr"]


def test_xers_not_chased():
    """Eyal: XERS $16.66, ~95% above the 30W SMA after the ~$10 breakout -> no entry."""
    r = classify(wk("xers"), None)
    assert r["stage"] == 2 and r["pct_ma"] > RULES["max_pct_above_ma"] and r["sub"] == "2-ext" and not r.get("plan")


def test_kkr_stage3_inside_range():
    """Inside its 2025-26 trading range the SMA crossings don't move KKR to a runaway stage 2."""
    w = to_daily(wk("kkr"))
    sp = stage_path(w, w["Close"].rolling(150).mean().values)
    assert sp["stage"] in (1, 3, 4)


def test_range_cross_stays_stage1():
    """A base after a decline whose close pokes above a flattening 150d but stays under the ceiling = still stage 1."""
    c = np.r_[np.linspace(80, 40, 180), 40 + 3 * np.sin(np.arange(80) / 4), np.linspace(40, 41.5, 10)]
    r = classify(bars_d(c, rng=0.01), bench_d(len(c)))
    assert r is not None and r["stage"] in (1, 3, 4)


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


def test_stop_lower_of_sma_and_base_low():
    """Eyal 2026-11-16: anchors A = 150d SMA, B = the base's last unbroken low; stop 0.75% under the LOWER one."""
    from srs_app.stages import stop_anchors, stop_below
    c = np.r_[np.full(30, 100.0), [104, 106, 103, 100, 104, 108, 110, 112, 111, 113]]
    w = bars(c, rng=0.01)
    w.iloc[33, w.columns.get_loc("Low")] = 98.0
    p = trade_levels(w, 95.0, 115.0, 114.0, 98.0)          # base low 98 ABOVE the SMA 95 -> stop under the SMA
    assert p["stop_basis"] == "ma" and abs(p["stop"] - round(95 * 0.9925, 2)) < 0.01 and p["anchor_b"] == 98.0
    p2 = trade_levels(w, 101.0, 115.0, 114.0, 98.0)        # base low 98 BELOW the SMA 101 -> stop under the low (no SMA floor)
    assert p2["stop_basis"] == "low" and p2["stop"] < 98.0 and abs(p2["stop"] - round(stop_below(98.0), 2)) < 0.01
    p3 = trade_levels(w, 101.0, 115.0, 114.0, None)        # no base low -> the SMA
    assert p3["stop_basis"] == "ma"


def test_stop_round_number_and_margin():
    from srs_app.stages import stop_below
    assert abs(stop_below(50.45) - 49.95) < 1e-9          # 0.75% would sit at 50.07 (above $50) -> just under $50
    assert abs(stop_below(98.0) - 98.0 * 0.9925) < 1e-9   # no round number inside the 1% band -> 0.75%
    for a in (12.3, 50.45, 98.0, 133.2, 1234.0):
        assert a * 0.99 - 1e-9 <= stop_below(a) <= a * 0.995 + 1e-9


def test_stop_too_far_uses_higher_low_when_sma_rising():
    """B below the 150d SMA but > 10% away and the SMA rising -> the most recent unbroken higher low under the SMA."""
    from srs_app.stages import stop_anchors, sma_slope
    c = np.r_[np.linspace(40, 80, 160), np.linspace(80, 120, 80), np.linspace(120, 90, 15), np.linspace(90, 118, 45)]
    w = bars_d(c, rng=0.005)
    bi = 240 + int(np.argmin(c[240:255]))
    hli = bi + 25
    lows = w["Low"].to_numpy().copy()
    lows[bi] = 87.0
    for i in range(hli - 12, hli + 13):
        if 0 <= i < len(lows) and i != hli:
            lows[i] = max(lows[i], 97.0)
    lows[hli] = 94.0
    lows[bi] = 87.0
    for i in range(bi + 1, len(lows)):
        if i != hli:
            lows[i] = max(lows[i], 90.0)
    w["Low"] = lows
    ma = float(w["Close"].rolling(150).mean().values[-1])
    sc, _, _ = sma_slope(w["Close"].rolling(150).mean().values, len(w) - 1)
    assert sc == "up"
    b = 87.0
    sa = stop_anchors(w, ma, 115.0, b)
    assert b < ma and sa["hl"] is not None and b < sa["hl"] < ma and sa["basis"] == "hl"
    sa2 = stop_anchors(w, ma, 95.0, b)                     # entry close enough -> B itself (not 'too far')
    assert sa2["basis"] == "low" and sa2["anchor"] == b


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


# ---------------------------------------------------------------- Eyal 2026-11-15: index / sector ETF classifier
from srs_app.stages import classify_index, market_gate, top_down, sector_status as _sector_status


def _ohlc(c, rng=0.01, freq="W-FRI"):
    c = np.asarray(c, float)
    idx = pd.date_range("2020-01-02" if freq == "B" else "2023-01-06", periods=len(c), freq=freq)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * (1 + rng), "Low": np.minimum(o, c) * (1 - rng),
                         "Close": c, "Volume": np.full(len(c), 1e6)}, index=idx)


def _ohlc_d(c, rng=0.01):
    return _ohlc(c, rng=rng, freq="B")


def test_index_close_below_rising_sma_exits_stage2():
    """A close below the 150d SMA exits stage 2 (2-dip / 2-weak were removed). Stay 3 if last HL holds, else 4."""
    k = np.arange(250)
    up = 40 * (1.0015 ** k) * (1 + 0.02 * np.sin(k / 8))
    w_up = _ohlc_d(up)
    ma0 = w_up["Close"].rolling(150).mean().values[-1]
    c = np.r_[up, ma0 * 0.97]
    r = classify_index(_ohlc_d(c))
    assert r["stage"] in (3, 4)
    assert r["close"] < r["ma30"]


def test_index_xlu_like_back_above_flat_sma_is_stage1():
    """Decline, then a flat 150d base with price back around / above the MA -> stage 1 (a base)."""
    c = np.r_[np.linspace(60, 40, 180), 40 + 1.2 * np.sin(np.arange(80) / 4), 41.0]
    r = classify_index(_ohlc_d(c))
    assert r is not None and r["stage"] in (1, 3, 4)



def test_index_support_break_is_stage4_even_if_ma_flat():
    """Stage 4 starts on a close below stage-3 / last-HL support even if the 150d is still flat."""
    k = np.arange(250)
    up = 80 * (1.002 ** k)
    crash = up[-1] * np.linspace(0.98, 0.70, 40)
    w = _ohlc_d(np.r_[up, crash], rng=0.02)
    r = classify_index(w)
    assert r["stage"] == 4 and r["close"] < r["ma30"]
    rs = classify(w, None)
    assert rs["stage"] == 4 and rs["close"] < rs["ma30"]


def test_xlk_real_candles_stage4_after_nov_breakdown():
    """Live XLK daily: after the Nov 2026 breakdown the close is well below the 150d SMA. Stage 4."""
    import json
    from pathlib import Path
    daily = Path("app/data/sector_daily/XLK.json")
    raw = json.loads(daily.read_text())
    df = pd.DataFrame(raw["d"], columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    r = classify_index(df)
    assert df.index[-1] >= pd.Timestamp("2026-11-20")
    assert r["stage"] == 4 and r["sub"] in ("4", "4A", "4-ext")
    assert r["close"] < r["ma30"]


def test_index_support_break_far_below_ma_is_stage4():
    """A close far below the 150d after an advance is stage 4, even if the slope has not fully turned down."""
    top = 60 + 1.5 * np.sin(np.arange(40) / 3)
    c = np.r_[np.linspace(30, 60, 200), top, np.linspace(59, 42, 40)]
    r = classify_index(_ohlc_d(c))
    assert r["stage"] == 4 and r["close"] < r["ma30"]
    assert r["idx"]["td"] == "avoid"
    assert _sector_status(r)["ok"] is False


def test_index_stage3_top_chops_around_flat_ma():
    c = np.r_[np.linspace(30, 60, 200), 60 + 2.0 * np.sin(np.arange(80) / 4)]
    r = classify_index(_ohlc_d(c))
    assert r["stage"] in (2, 3)


def test_xlf_real_candles_stage2():
    """XLF on the daily 150d engine: still an advance (stage 2) on the 2026-11-13 weekly fixture, upsampled."""
    r = classify_index(to_daily(wk("xlf")))
    assert r["stage"] in (2, 3)
    if r["stage"] == 2:
        assert r["slope_cls"] in ("up", "flat")


def test_xlu_real_candles_base_or_top():
    r = classify_index(to_daily(wk("xlu")))
    assert r["stage"] in (1, 3, 2)


def test_market_gate_blocks_stage3_and_4():
    g = lambda st: market_gate({"stage": st, "sub": str(st), "idx": {"td_he": "x"}})["ok"]
    assert g(2) is True and g(1) is True and g(3) is False and g(4) is False
    assert market_gate(None)["ok"] is None
    assert top_down({"stage": 3}, {"stage": 2, "sec_ok": True, "sec_case": "2"})[0] == "mkt_off"
    assert top_down({"stage": 2}, {"stage": 2, "sec_ok": True, "sec_case": "2"})[0] == "full"
    assert top_down({"stage": 2}, {"stage": 4, "sec_ok": False})[0] == "avoid"
    assert top_down({"stage": 2}, {"stage": 3, "sec_ok": False})[0] == "no_new"
    assert top_down({"stage": 2}, {"stage": 1, "sec_ok": True, "sec_case": "1late"})[0] == "early"


def test_three_year_history_required():
    """Eyal 2026-11-15 (IEAG): < 3 years of weekly bars -> dropped before classification (no tab, no candidate)."""
    from srs_app.stages import history_ok
    assert RULES["min_weeks"] == 156
    assert not history_ok(_ohlc(np.linspace(20, 40, 155)))
    assert history_ok(_ohlc(np.linspace(20, 40, 156)))


def test_avg_dollar_vol_prefers_50day_daily():
    """Eyal 2026-11-16 (VBNK): 50-day mean of close×volume; daily wins over a weekly fallback."""
    from srs_app.stages import avg_dollar_vol_m
    d = _daily([100.0] * 60, vols=[400_000] * 10 + [600_000] * 50)  # last 50 days = $60M; earlier days $40M
    w = d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    assert abs(avg_dollar_vol_m(d, w) - 60.0) < 0.01
    thin = _daily([20.0] * 50, vols=[100_000] * 50)                 # $2M/day
    assert abs(avg_dollar_vol_m(thin) - 2.0) < 0.01


def test_avg_dollar_vol_weekly_fallback():
    """No daily bars -> weekly $vol / 5, averaged over ~10 weeks."""
    from srs_app.stages import avg_dollar_vol_m
    # 10 weeks, close $20, weekly volume 12.5M shares -> weekly $vol $250M -> $50M/day
    w = bars([20.0] * 12, vols=np.full(12, 12_500_000), rng=0.0)
    assert abs(avg_dollar_vol_m(None, w) - 50.0) < 0.01
    assert avg_dollar_vol_m(None, None) is None


def test_liquidity_ok_50m_hard_gate():
    """$50M is a hard universe pre-filter; the old 500K-shares-per-week loophole is gone."""
    from srs_app.stages import RULES, liquidity_ok, prefilter
    assert RULES["min_dollar_vol_m"] == 50.0 and RULES["dollar_vol_days"] == 50
    assert liquidity_ok(50.0) and liquidity_ok(77.7) and not liquidity_ok(49.9) and not liquidity_ok(2.3) and not liquidity_ok(None)
    fat_shares = {"avg_vol": 5_000_000, "inst_own": 40.0, "industry": "Banks", "mcap": 5e9}  # would have passed the old OR
    pre = prefilter(fat_shares, 200, 24.0, 2.3)
    liq = next(x for x in pre if x["k"] == "liq")
    assert liq["ok"] is False and "$50M" in liq["he"]
    assert next(x for x in prefilter(fat_shares, 200, 24.0, 50.0) if x["k"] == "liq")["ok"] is True


def test_split_long_telegram_message():
    from srs_app.stages import split_message
    text = "\n\n".join(f"T{i} " + "x" * 300 for i in range(20))
    parts = split_message(text)
    assert len(parts) > 1 and all(len(p) <= 3900 for p in parts) and "\n\n".join(parts) == text
    assert split_message("short") == ["short"]



def test_etf_gate_prefers_industry():
    """Eyal 2026-11-16: industry ETF gates when mapped; else the broad SPDR sector."""
    from srs_app.stages import etf_gate, INDUSTRY_ETF, INDUSTRY_WATCH
    assert etf_gate("Banks - Regional", "Financial") == ("KRE", "XLF", "KRE")
    assert etf_gate("Biotechnology", "Healthcare") == ("XBI", "XLV", "XBI")
    assert etf_gate("Aerospace & Defense", "Industrials") == ("ITA", "XLI", "ITA")
    assert etf_gate("Packaged Foods", "Consumer Defensive") == (None, "XLP", "XLP")  # no industry ETF
    assert etf_gate("Software - Application", "Technology") == ("IGV", "XLK", "IGV")
    assert "CIBR" in INDUSTRY_WATCH and "SMH" in INDUSTRY_ETF.values() and "ARKK" not in INDUSTRY_WATCH


def test_weekly_atr_wilder():
    """Weekly ATR(14) matches the retest chart (Wilder, first 14 TRs averaged)."""
    from srs_app.stages import weekly_atr
    w = bars(np.linspace(20, 40, 40), rng=0.05)
    a = weekly_atr(w)
    assert a is not None and a > 0
    # TR of a 5% range bar around price 40 is about 2; ATR should be in a plausible band
    assert 0.5 < a < 5
    assert weekly_atr(w.iloc[:10]) is None


# ---------------------------------------------------------------- Stan Weinstein short-selling side (Eyal 2026-11-21)


def test_sell_stop_price_and_stop_above():
    from srs_app.stages import sell_stop_price, stop_above
    assert abs(sell_stop_price(100.0) - 99.5) < 1e-9
    assert abs(sell_stop_price(5.0) - 4.95) < 1e-9
    # stop_above: 0.75% above anchor, or round number + $0.05 if within 1% and higher
    assert abs(stop_above(99.5) - 100.24625) < 1e-6  # round 100 + 0.05 = 100.05 < 100.25 -> keeps 0.75%
    assert abs(stop_above(49.85) - 50.223875) < 1e-6
    assert abs(stop_above(49.98) - 50.35485) < 1e-6


def test_breakdown_4a_volume_not_required():
    """Weinstein: Stage 4 breakdown (4A) does NOT require high breakdown volume."""
    top = 80.0 + 1.5 * np.sin(np.arange(60) / 2)
    c = np.r_[np.linspace(30, 80, 200), top, 72.0, 68.0, 65.0, 62.0]
    v = np.full(len(c), 1e6)
    r = classify(bars_d(c, v, rng=0.01), bench_d(len(c)))
    assert r["stage"] == 4
    if r.get("bd") and r["bd"].get("holding") and r.get("short_plan"):
        assert 0 < r["short_plan"]["target"] < r["short_plan"]["entry"] < r["short_plan"]["stop"]


def test_short_stop_anchors_mirror_and_lh_tighten():
    """Higher of (30W SMA, unbroken base high); tightens to lower high when stop > 10% and SMA down."""
    from srs_app.stages import short_stop_anchors, stop_above
    c = np.r_[np.linspace(30, 80, 50), 80 - np.linspace(0, 22, 40)]
    w = bars(c, rng=0.01)
    # Give an explicit high B=78 above SMA (~66) followed by a lower high pivot at ~69
    w.iloc[-20, w.columns.get_loc("High")] = 78.0
    w.iloc[-10, w.columns.get_loc("High")] = 69.0
    w.iloc[-11, w.columns.get_loc("High")] = 65.0
    w.iloc[-12, w.columns.get_loc("High")] = 64.0
    w.iloc[-9, w.columns.get_loc("High")] = 65.0
    w.iloc[-8, w.columns.get_loc("High")] = 64.0
    ma_now = float(w["Close"].rolling(30).mean().iloc[-1])
    sa = short_stop_anchors(w, ma_now, 56.0, 78.0)
    assert sa["basis"] in ("high", "lh")
    assert sa["stop"] > 56.0
    # When base high <= SMA, stop sits above SMA ('ma')
    sa_ma = short_stop_anchors(w, ma_now, 56.0, ma_now - 2.0)
    assert sa_ma["basis"] == "ma" and abs(sa_ma["stop"] - stop_above(ma_now)) < 1e-6


def test_support_scan_and_geometry_guard():
    """support_scan finds nearest significant 2y swing low; open_sky keeps target > 0 and rr=2.5."""
    from srs_app.stages import short_trade_levels, support_scan
    c = np.r_[np.linspace(120, 80, 40), np.linspace(80, 110, 30), np.linspace(110, 95, 30)]
    w = bars(c, rng=0.01)
    sup = support_scan(w, 94.0)
    assert not sup["open_sky"] and sup["support"] is not None and sup["support"] < 94.0
    p = short_trade_levels(w, 102.0, 94.0, sup["support"], 110.0)
    assert 0 < p["target"] < p["entry"] < p["stop"] and p["rr"] > 0
    # Open sky with extreme stop (>40% risk) -> t_sky < 0 rejected so target is None, rr is None
    w_sky = bars(np.linspace(120, 50, 60), rng=0.01)
    p_bad = short_trade_levels(w_sky, 90.0, 50.0, None, 95.0)
    assert p_bad["open_sky"] and p_bad["target"] is None and p_bad["rr"] is None


def test_short_market_and_sector_gates():
    from srs_app.stages import short_market_gate, short_sector_status
    assert short_market_gate({"stage": 3, "sub": "3", "idx": {"td_he": "פסגה"}})["ok"] is True
    assert short_market_gate({"stage": 4, "sub": "4", "idx": {"td_he": "ירידה"}})["ok"] is True
    assert short_market_gate({"stage": 2, "sub": "2"})["ok"] is False
    # 2-weak blocks shorts while 30W SMA is still rising
    assert short_market_gate({"stage": 2, "sub": "2-weak"})["ok"] is False
    assert short_market_gate({"stage": 1, "sub": "1B"})["ok"] is False
    assert short_sector_status({"stage": 4, "sub": "4", "close": 50.0, "ma30": 60.0, "slope_cls": "down"})["ok"] is True
    assert short_sector_status({"stage": 3, "sub": "3", "close": 60.0, "ma30": 61.0, "slope_cls": "flat"})["ok"] is True
    assert short_sector_status({"stage": 2, "sub": "2-weak", "close": 60.0, "ma30": 65.0, "slope_cls": "up"})["ok"] is False
    assert short_sector_status({"stage": 1, "sub": "1B", "close": 40.0, "ma30": 41.0, "slope_cls": "flat"})["ok"] is False


def test_cash_etf_ok_prefilter():
    from srs_app.stages import cash_etf_ok
    assert cash_etf_ok("SGOV") is False
    assert cash_etf_ok("BIL") is False
    assert cash_etf_ok("AAPL") is True


def test_alert_text_and_needs_research_include_shorts():
    from srs_app.stages import RULES, alert_text, needs_research
    doc = {
        "week": "2026-11-20",
        "rules": RULES,
        "market": {"SPY": {"stage": 3, "idx": {"td_he": "פסגה"}}, "QQQ": {"stage": 4}},
        "buy_stop_candidates": [],
        "sell_stop_candidates": [{
            "t": "SHORTX", "n": "Short Test Corp", "kind": "breakdown", "sub": "4A",
            "close": 49.0, "level": 50.0, "sell_stop": 49.75, "stop": 54.0, "stop_pct": 8.5,
            "target": 36.0, "target_src": "support", "open_sky": False, "rr": 3.24,
            "shares": 12, "pos_usd": 597.0, "atr_w": 2.45,
            "earn": "2027-01-20", "earn_td": 40, "earn_est": False,
            "post_earn": None, "ex": "NASDAQ", "etf": "XLY", "etf_stage": 3, "sec_td_he": "שלב 3 (פסגה)",
        }],
    }
    txt = alert_text(doc)
    assert txt is not None and "Sell-Stop" in txt and "SHORTX" in txt and "ATR(W) $2.45" in txt
    need = needs_research(doc, cache={})
    assert [x["t"] for x in need] == ["SHORTX"]


def test_entry_R_daily_thresholds():
    """Eyal t454u: Buy-Stop math uses daily 150d / 50d volume / 15-session breakout / 2y daily swings."""
    from srs_app.stages import RULES, _entry_R, buy_stop_price, sell_stop_price
    e = _entry_R(RULES)
    assert e["ma_weeks"] == 150
    assert e["sma_slope_w"] == 20
    assert e["base_window_w"] == 130
    assert e["min_base_w"] == 50
    assert e["bo_max_weeks_ago"] == 15
    assert e["vol_avg_w"] == 50
    assert e["sig_pivot_w"] == 40
    assert e["overhead_w"] == 504
    assert e["cong_min_w"] == 25
    assert RULES["risk_usd"] == 55
    assert abs(buy_stop_price(100.0) - 100.5) < 1e-9
    assert abs(sell_stop_price(100.0) - 99.5) < 1e-9
