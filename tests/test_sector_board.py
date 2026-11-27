"""Sector board badge, filters, and recommendations (srs_app.sector_board, T-7)."""
from srs_app.sector_board import (
    board_badge, flag_near_res, flag_near_sup, flag_retest2, flag_retest4, recommend, flags_of,
    resistance_of, support_of, top_stocks, filter_lists, last_breakout_level, etf_as_stock,
)
from srs_app.stages import buy_stop_price, stop_below, RULES


def _row(**kw):
    base = dict(t="TEST", n="Test", stage=1, sub="1B", close=100.0, ma30=95.0, atr_w=4.0,
                sec="Technology", sec_etf="XLK", mcap_b=10.0,
                range={"ceil": 105.0, "floor": 90.0, "since_w": 12, "since": "2026-08-01"},
                base={"top": 105.0, "low": 90.0, "weeks": 12, "dist_pct": 4.8, "mature": True})
    base.update(kw)
    return base


def test_badge_2a_is_above_ma_before_breakout():
    r = _row(stage=1, sub="1B", close=100, ma30=95, base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 4.8})
    assert board_badge(r) == "2a"


def test_badge_2a_not_used_for_pipeline_2A_breakout():
    # pipeline sub 2A is a fresh stage-2 breakout — badge stays "2"
    r = _row(stage=2, sub="2A", close=110, ma30=95, base=None,
             range={"ceil": 120, "floor": 105, "since_w": 1, "since": "2026-11-13"},
             bo={"level": 105, "weeks_ago": 1})
    assert board_badge(r) == "2"


def test_badge_stage1_below_ma_is_1():
    assert board_badge(_row(stage=1, close=90, ma30=95)) == "1"


def test_badge_other_stages():
    assert board_badge(_row(stage=2, close=110, ma30=95)) == "2"
    assert board_badge(_row(stage=3, close=100, ma30=102)) == "3"
    assert board_badge(_row(stage=4, close=80, ma30=95)) == "4"


def test_near_resistance_2a_filter():
    near = _row(stage=1, close=101, ma30=95, base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 3.8})
    far = _row(stage=1, close=90, ma30=85, base={"top": 105, "low": 80, "weeks": 12, "dist_pct": 14.3})
    assert flag_near_res(near) is True
    assert flag_near_res(far) is False
    # already broke out — not 2a
    assert flag_near_res(_row(stage=2, close=104, ma30=95, base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 1})) is False


def test_stage3_near_support_filter():
    near = _row(stage=3, close=94, ma30=100,
                short_base={"floor": 90, "top": 110, "weeks": 8, "dist_pct": 4.4},
                range={"ceil": 110, "floor": 90, "since_w": 8, "since": "2026-09-01"})
    far = _row(stage=3, close=108, ma30=100,
               short_base={"floor": 90, "top": 110, "weeks": 8, "dist_pct": 20},
               range={"ceil": 110, "floor": 90, "since_w": 8, "since": "2026-09-01"})
    assert flag_near_sup(near) is True
    assert flag_near_sup(far) is False
    assert flag_near_sup(_row(stage=2, close=94, ma30=90,
                              range={"ceil": 110, "floor": 90, "since_w": 8, "since": "x"})) is False


def test_stage2_retest_of_broken_resistance():
    # recorded breakout at 100, close sitting on it
    r = _row(stage=2, sub="2", close=101, ma30=90, bo={"level": 100, "weeks_ago": 4},
             range={"ceil": 115, "floor": 100, "since_w": 4, "since": "x"}, base=None)
    assert flag_retest2(r) is True
    # extended, not a retest
    r2 = _row(stage=2, close=130, ma30=90, bo={"level": 100, "weeks_ago": 10},
              range={"ceil": 135, "floor": 100, "since_w": 10, "since": "x"}, base=None)
    assert flag_retest2(r2) is False
    # stage 1 is not a stage-2 retest
    assert flag_retest2(_row(stage=1, close=101, ma30=90, bo={"level": 100})) is False


def test_stage4_retest_requires_breakdown_level():
    r = _row(stage=4, sub="4", close=99, ma30=110, bd={"level": 100, "weeks_ago": 3},
             range={"ceil": 100, "floor": 80, "since_w": 3, "since": "x"}, base=None)
    assert flag_retest4(r) is True
    # sitting on new lows without a recorded breakdown is not a retest of broken support
    lows = _row(stage=4, close=81, ma30=110, bd=None,
                range={"ceil": 120, "floor": 80, "since_w": 0, "since": "x"}, base=None)
    assert flag_retest4(lows) is False


def test_recommend_2a_near_resistance_is_buy_stop():
    r = _row(stage=1, close=101, ma30=95, base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 3.8})
    rec = recommend(r, "2a", flags_of(r, "2a"))
    assert rec["kind"] == "buy_stop"
    assert rec["entry"] == round(buy_stop_price(105, RULES), 2)
    assert rec["stop"] == round(stop_below(min(95, 90), RULES), 2)
    assert "Buy-Stop" in rec["he"]
    assert "לא מציבה פקודות" in rec["he"]


def test_recommend_stage1_below_ma_waits_for_sma():
    r = _row(stage=1, close=90, ma30=95)
    rec = recommend(r, "1", flags_of(r, "1"))
    assert rec["kind"] == "wait_sma"
    assert "150" in rec["he"]


def test_recommend_retest2_is_limit():
    r = _row(stage=2, close=101, ma30=90, bo={"level": 100, "weeks_ago": 4},
             range={"ceil": 115, "floor": 100, "since_w": 4, "since": "x"}, base=None)
    rec = recommend(r, "2", flags_of(r, "2"))
    assert rec["kind"] == "limit_retest"
    assert rec["entry"] == 100
    assert "לימיט" in rec["he"]
    assert "לא מציבה פקודות" in rec["he"]


def test_recommend_stage3_near_support_is_sell_stop():
    r = _row(stage=3, close=94, ma30=100,
             short_base={"floor": 90, "top": 110, "weeks": 8, "dist_pct": 4.4},
             range={"ceil": 110, "floor": 90, "since_w": 8, "since": "x"}, base=None)
    rec = recommend(r, "3", flags_of(r, "3"))
    assert rec["kind"] == "sell_stop"
    assert "Sell-Stop" in rec["he"]


def test_top_stocks_by_mcap():
    rows = [_row(t=f"T{i}", sec_etf="XLK", mcap_b=float(i), stage=2) for i in range(15)]
    rows.append(_row(t="OTHER", sec_etf="XLF", mcap_b=999, stage=2))
    tops = top_stocks(rows, "XLK", 10)
    assert [r["t"] for r in tops] == [f"T{i}" for i in range(14, 4, -1)]


def test_filter_lists_keys():
    rows = [
        _row(t="A", stage=1, close=101, ma30=95, base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 3.8}),
        _row(t="B", stage=3, close=94, ma30=100, short_base={"floor": 90, "top": 110, "weeks": 8, "dist_pct": 4.4},
             range={"ceil": 110, "floor": 90, "since_w": 8, "since": "x"}, base=None),
        _row(t="C", stage=2, close=101, ma30=90, bo={"level": 100, "weeks_ago": 4},
             range={"ceil": 115, "floor": 100, "since_w": 4, "since": "x"}, base=None),
        _row(t="D", stage=4, close=99, ma30=110, bd={"level": 100, "weeks_ago": 3},
             range={"ceil": 100, "floor": 80, "since_w": 3, "since": "x"}, base=None),
    ]
    fl = filter_lists(rows)
    assert fl["2a_res"] == ["A"]
    assert fl["3_sup"] == ["B"]
    assert fl["retest2"] == ["C"]
    assert fl["retest4"] == ["D"]


def test_resistance_prefers_base_top():
    r = _row(base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 4},
             range={"ceil": 99, "floor": 80, "since_w": 1, "since": "x"})
    assert resistance_of(r) == 105
    assert support_of(_row(short_base={"floor": 88, "top": 110, "weeks": 4, "dist_pct": 1},
                           range={"ceil": 110, "floor": 80, "since_w": 1, "since": "x"})) == 88


def test_stage2_without_breakout_level_is_not_retest():
    mid = _row(stage=2, close=108, ma30=90, bo=None,
               range={"ceil": 120, "floor": 100, "since_w": 10, "since": "x"}, base=None)
    assert flag_retest2(mid) is False
    low = _row(stage=2, close=102, ma30=90, bo=None,
               range={"ceil": 120, "floor": 100, "since_w": 10, "since": "x"}, base=None)
    assert flag_retest2(low) is False
    derived = _row(stage=2, close=102, ma30=90, bo=None, _bo_lvl=100,
                   range={"ceil": 120, "floor": 100, "since_w": 10, "since": "x"}, base=None)
    assert flag_retest2(derived) is True


def test_board_near_is_one_weekly_atr_not_five_percent():
    """Board filters use 1 weekly ATR, not RULES.pre_bo_pct (5%)."""
    assert RULES["pre_bo_pct"] == 5.0
    # 4.3% under the ceiling (would pass the 5% Buy-Stop window) but 4.5 > ATR 4
    far_for_atr = _row(stage=1, close=100.5, ma30=95, atr_w=4.0,
                       base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 4.3})
    assert flag_near_res(far_for_atr) is False
    close_enough = _row(stage=1, close=101.5, ma30=95, atr_w=4.0,
                        base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 3.3})
    assert flag_near_res(close_enough) is True  # $3.50 <= $4 ATR
    no_atr = _row(stage=1, close=101, ma30=95, atr_w=None,
                  base={"top": 105, "low": 90, "weeks": 12, "dist_pct": 3.8})
    assert flag_near_res(no_atr) is False
    # stage-3 / retests follow the same ATR window
    sup_far = _row(stage=3, close=100.5, ma30=110, atr_w=4.0,
                   short_base={"floor": 90, "top": 110, "weeks": 8, "dist_pct": 11.7},
                   range={"ceil": 110, "floor": 90, "since_w": 8, "since": "x"}, base=None)
    assert flag_near_sup(sup_far) is False  # $10.50 > $4
    retest_far = _row(stage=2, close=106, ma30=90, atr_w=4.0, bo={"level": 100, "weeks_ago": 4},
                      range={"ceil": 115, "floor": 100, "since_w": 4, "since": "x"}, base=None)
    assert flag_retest2(retest_far) is False  # $6 > $4; was 6% so also outside 5%, use 104
    retest_mid = _row(stage=2, close=104.5, ma30=90, atr_w=4.0, bo={"level": 100, "weeks_ago": 4},
                      range={"ceil": 115, "floor": 100, "since_w": 4, "since": "x"}, base=None)
    assert flag_retest2(retest_mid) is False  # $4.50 > $4 ATR, but 4.5% would have passed the old 5% rule
    retest_ok = _row(stage=2, close=103.5, ma30=90, atr_w=4.0, bo={"level": 100, "weeks_ago": 4},
                     range={"ceil": 115, "floor": 100, "since_w": 4, "since": "x"}, base=None)
    assert flag_retest2(retest_ok) is True


def test_etf_as_stock_is_marked_sector():
    e = dict(stage=2, sub="2", close=230.0, ma30=210.0, atr_w=5.0,
             range={"ceil": 240.0, "floor": 200.0, "since_w": 10, "since": "x"})
    card = etf_as_stock("XLK", e, hist_start="2016-11-28", hist_days=2513)
    assert card["is_sector"] is True
    assert card["t"] == "XLK"
    assert card["badge"] == "2"
    assert card["etf"] == "XLK"
    assert card["n"]  # Hebrew sector name
    assert card["rec"]["he"]
    assert "לא מציבה פקודות" in card["rec"]["he"]
    assert card["hist_start"] == "2016-11-28"
