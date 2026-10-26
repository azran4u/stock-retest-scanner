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
