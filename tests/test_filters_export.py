"""App filters data (Eyal 2026-10-26): per-kind last reversal dates (report_filters.last_reversals,
export_data.attach_reversals) and the rules page JSON (srs_app.rules)."""
import numpy as np
import pandas as pd

import report_filters as rf
import smooth_support_analysis as ssa
import stock_screen as ss
from srs_app import export_data as ed
from srs_app import rules


def _daily(n=400, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-03-03", periods=n)
    c = 50 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))
    o = c * (1 + rng.normal(0, 0.01, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.012, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.012, n)))
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": 1e6}, index=idx)


def _shapes(b, i, atr):
    return ssa.weekly_reversal_shapes(float(b.Open.iloc[i]), float(b.High.iloc[i]), float(b.Low.iloc[i]), float(b.Close.iloc[i]),
                                      float(b.Open.iloc[i - 1]), float(b.Close.iloc[i - 1]),
                                      float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else float("nan"))


def test_last_reversals_is_most_recent_per_kind():
    b = _daily()
    out = rf.last_reversals(b, 60)
    assert out, "random walk has some reversal candles"
    atr = ss.atr_series(b, 14)
    pos = {str(d.date()): i for i, d in enumerate(b.index)}
    for k, d in out.items():
        i = pos[d]
        assert i >= len(b) - 60
        assert _shapes(b, i, atr)[rf._KIND_KEY[k]], k
        assert not any(_shapes(b, j, atr)[rf._KIND_KEY[k]] for j in range(i + 1, len(b))), f"{k}: a later candle exists"
    for k in set(rf.CONFIG["reversal_kinds"]) - set(out):
        assert not any(_shapes(b, j, atr)[rf._KIND_KEY[k]] for j in range(len(b) - 60, len(b)))


def test_last_reversals_lookback_and_empty():
    b = _daily()
    one = rf.last_reversals(b, 1)
    assert all(d == str(b.index[-1].date()) for d in one.values())
    assert rf.last_reversals(None, 10) == {} and rf.last_reversals(b.iloc[:1], 10) == {}


def test_attach_reversals_rows():
    b = _daily()
    rows = [{"ticker": "AAA"}, {"ticker": "NOPE"}]
    ed.attach_reversals(rows, asof_date=str(b.index[-1].date()), hist={"AAA": b}, weeks=26)
    assert rows[1]["rev_d"] == {} and rows[1]["rev_w"] == {}
    assert rows[0]["rev_d"] and set(rows[0]["rev_d"]) <= set(rf.CONFIG["reversal_kinds"])
    cut = str((b.index[-1] - pd.Timedelta(weeks=27)).date())
    assert all(d >= cut for d in list(rows[0]["rev_d"].values()) + list(rows[0]["rev_w"].values()))


def test_rules_json_from_code(tmp_path):
    p = tmp_path / "ss.py"
    p.write_text('SCREENER_URL = (\n    "https://finviz.com/screener?v=111&f=sh_price_o10,"\n    "ta_sma50_pb&ft=4&o=ticker"\n)\n')
    s = rules.screener_filters(p)
    assert [f["code"] for f in s["filters"]] == ["sh_price_o10", "ta_sma50_pb"]
    assert s["filters"][0]["he"] == "מחיר מעל $10"
    j = rules.build_rules()
    assert j["core"] == list(rf.CORE_FILTERS) and j["info"] == list(rf.WARN_FILTERS) and "wait" not in j
    assert j["t"]["rr_min"] == rf.CONFIG["rr_min"] and j["t"]["dollar_vol_min"] == rf.CONFIG["dollar_vol_min"]
    assert "ta_sma200_pa" not in [f["code"] for f in j["screener"]["filters"]], "SMA200 dropped 2026-10-26"
    assert j["sizing"] == {"account_usd": 5000, "risk_pct": 1.1, "max_risk_usd": 55.0}, "max risk $55 / trade (2026-10-26)"
    b = j["bot"]
    assert b["rule_version"] == "v5-2026-10-26" and b["zone_scoring"] == "v5" and "structure_exclude_weeks" not in b


# ---- reversal candle touching the level (Eyal 2026-10-31): export candles + live zone gate ----
def test_reversal_candles_shapes_and_mask():
    b = _daily()
    c = rf.reversal_candles(b, 60)
    assert c and all(0 <= k < 60 for k, *_ in c)
    assert [k for k, *_ in c] == sorted(k for k, *_ in c), "newest first"
    atr = ss.atr_series(b, 14)
    order = list(rf.CONFIG["reversal_kinds"])
    for k, mask, lo, cl, a in c:
        i = len(b) - 1 - k
        assert abs(lo - b.Low.iloc[i]) < 1e-3 and abs(cl - b.Close.iloc[i]) < 1e-3
        sh = _shapes(b, i, atr)
        assert mask == sum(1 << j for j, kk in enumerate(order) if sh[rf._KIND_KEY[kk]])
    # bars without any shape are not listed
    ks = {k for k, *_ in c}
    assert all(not any(_shapes(b, len(b) - 1 - k, atr)[rf._KIND_KEY[kk]] for kk in order) for k in range(1, 60) if k not in ks)


def test_at_zone_matches_scan_reversals_gate():
    """the app's live gate (at_zone on exported candles) == report_filters._scan_reversals (E1/E2 zone gate)."""
    for seed in (3, 7, 11):
        b = _daily(seed=seed)
        cands = rf.reversal_candles(b, 60)
        px = float(b.Close.iloc[-1])
        for lo_f, hi_f in ((0.80, 0.85), (0.9, 0.95), (0.95, 1.0), (1.0, 1.05), (0.6, 0.65)):
            zone = (px * lo_f, px * hi_f)
            for L in (1, 3, 5, 10, 26, 60):
                assert rf.at_zone(cands, zone, L) == rf._scan_reversals(b, L, zone)[0], (seed, zone, L)
    assert rf.at_zone(cands, None, 60) is False


def test_at_zone_kinds_and_window():
    cands = [[0, 1, 99.0, 101.0, 2.0], [4, 2, 90.0, 92.0, 2.0]]
    z = (95.0, 100.0)
    assert rf.at_zone(cands, z, 1) and rf.at_zone(cands, z, 1, ["hammer"]) and not rf.at_zone(cands, z, 1, ["engulfing"])
    # engulfing 4 bars back: low 90 < bottom 95 - 0.5*2 and close 92 < 95 -> under the zone, not touching
    assert not rf.at_zone(cands, z, 5, ["engulfing"])
    assert rf.at_zone([[2, 4, 101.0, 103.0, 2.0]], z, 3) and not rf.at_zone([[2, 4, 101.5, 103.0, 2.0]], z, 3)
    assert not rf.at_zone([[2, 4, 99.0, 103.0, 2.0]], z, 2), "outside the window"


def test_attach_reversals_candles():
    b = _daily()
    rows = [{"ticker": "AAA"}, {"ticker": "NOPE"}]
    ed.attach_reversals(rows, asof_date=str(b.index[-1].date()), hist={"AAA": b}, weeks=26)
    assert rows[1]["rev_dc"] == [] and rows[1]["rev_wc"] == []
    assert rows[0]["rev_dc"] and all(k < ed.REV_ZONE_DAYS for k, *_ in rows[0]["rev_dc"])
    assert all(k < 26 for k, *_ in rows[0]["rev_wc"])


def test_kind_bit_order_matches_app():
    """mask bits = REV_KINDS order in webapp/src/filters.ts"""
    from pathlib import Path
    import re
    ts = (Path(__file__).resolve().parent.parent / "webapp/src/filters.ts").read_text()
    app = re.search(r"REV_KINDS = \[([^\]]*)\]", ts).group(1)
    assert [x.strip().strip("'") for x in app.split(",")] == list(rf.CONFIG["reversal_kinds"])
