"""Eyal 2026-11-16: cash / money-market / short-term bond ETFs are never candidates (list + weekly ATR < 1% guard for
funds); and no plan may have SL <= 0, SL >= entry or TP <= entry (AXTI sl -8.23)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

import report_filters as rf
import stock_screen as ss
from srs_app.bot_drawings import valid_geometry

TODAY = date(2026, 11, 17)


def _daily(vol_pct, price=100.0, n=800, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-11-17", periods=n)
    c = price * np.exp(np.cumsum(rng.normal(0, vol_pct / 100, n)))
    return pd.DataFrame({"Open": c, "High": c * (1 + vol_pct / 200), "Low": c * (1 - vol_pct / 200), "Close": c,
                         "Volume": 5e6}, index=idx)


@pytest.mark.parametrize("t", ["ICSH", "SPTS", "VGSH", "FLOT", "PULS", "SPSB", "SRLN", "BIL", "SGOV", "SHV", "SHY",
                               "USFR", "TFLO", "JPST", "MINT"])
def test_listed_cash_etfs_out(t):
    assert t in rf.CASH_BOND_ETFS
    r = rf.compute_row(t, _daily(1.5), TODAY, None, None, earnings_kind="none")
    assert r["f_not_cash_etf"] is False


def test_generic_low_atr_fund_out_stock_kept(monkeypatch):
    monkeypatch.setattr(ss, "is_fund", lambda t: t == "NEWBOND")
    r = rf.compute_row("NEWBOND", _daily(0.05), TODAY, None, None, earnings_kind="none")
    assert r["weekly_atr_pct"] < 1 and r["f_not_cash_etf"] is False
    r = rf.compute_row("CALMCO", _daily(0.05), TODAY, None, None, earnings_kind="none")   # not a fund: kept
    assert r["f_not_cash_etf"] is True
    r = rf.compute_row("SPYX", _daily(1.5), TODAY, None, None, earnings_kind="none")      # equity-like vol: kept
    assert r["f_not_cash_etf"] is True
    assert "f_not_cash_etf" in rf.CORE_FILTERS


@pytest.mark.parametrize("e,s,t,ok", [(10, 9, 12, True), (10, -8.23, 12, False), (10, 0, 12, False),
                                      (10, 10, 12, False), (10, 11, 12, False), (10, 9, 10, False),
                                      (10, 9, 9, False), (None, 9, 12, False)])
def test_valid_geometry(e, s, t, ok):
    assert valid_geometry(e, s, t) is ok
