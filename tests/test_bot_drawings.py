"""Bot drawings: v3d golden regression (levels must reproduce), candidate selection, SQL format."""
import json
from pathlib import Path

import pytest

from srs_app import bot_drawings as B
from srs_app.sync import sql_insert_bot_drawing

GOLD = json.loads((Path(__file__).parent / "data" / "bot_drawings_golden.json").read_text())["rows"]
HAVE_RULES = (B.LEARN_DIR / "infer_v3d.py").exists() and Path("/workspace/hist_cache.pkl").exists()


@pytest.mark.skipif(not HAVE_RULES, reason="needs /workspace/drawing-learn + hist_cache.pkl")
@pytest.mark.parametrize("g", GOLD, ids=[g["ticker"] for g in GOLD])
def test_v3d_golden(g):
    r = B.compute(g["ticker"], g["data_date"])
    assert r["has_level"]
    for a, b in (("zone_bottom", "zone_bottom"), ("zone_top", "zone_top"), ("entry", "entry"), ("stop", "sl"), ("target", "tp")):
        assert abs(r[a] - g[b]) < 0.02, (a, r[a], g[b])
    assert r["why"]["branch"] == g["kind"] and r["why"]["pivot_date"] == g["pivot_date"]
    # Long Position time anchor: the week after the last candle, 20 weekly bars wide
    assert r["t_start"] > g["data_date"] and len(r["t_end"]) == 10


REP = {"f_dollar_vol": True, "f_history": True, "f_no_earnings_14d": True, "f_technical": True}


def test_plan_selection():
    rows = [dict(REP, ticker=t) for t in ("NEW", "MINE", "TVD", "NI", "STRUCT", "BOTOK", "BOTBROKE", "REJ", "REJOLD")]
    rows.append(dict(REP, ticker="LOWVOL", f_dollar_vol=False))
    rows.append(dict(REP, ticker="NOTECH", f_technical=False))
    rows.append(dict(REP, ticker="LINES", tv_source="user-lines"))
    dr = [
        {"id": "1", "ticker": "MINE", "kind": "zone", "source": "user", "status": "active"},
        {"id": "2", "ticker": "TVD", "kind": "long", "source": "tv", "status": "active", "stop": 1},
        {"id": "3", "ticker": "BOTOK", "kind": "long", "source": "bot", "status": "active", "stop": 10, "created_at": "2026-10-01"},
        {"id": "4", "ticker": "BOTBROKE", "kind": "long", "source": "bot", "status": "active", "stop": 10, "created_at": "2026-10-01"},
        {"id": "5", "ticker": "BOTBROKE", "kind": "zone", "source": "bot", "status": "active", "created_at": "2026-10-01"},
        {"id": "6", "ticker": "REJ", "kind": "zone", "source": "bot", "status": "rejected", "meta": {"rule_version": B.RULE_VERSION}},
        {"id": "7", "ticker": "REJOLD", "kind": "zone", "source": "bot", "status": "rejected", "meta": '{"rule_version": "v0"}'},
    ]
    labels = [{"ticker": "NI", "label": "not_interesting", "value": "yes", "until": "2026-12-01"}]
    fb = [{"ticker": "STRUCT", "category": "structure", "created_at": "2026-10-20T10:00:00+00:00"}]
    lows = {"BOTOK": 11.0, "BOTBROKE": 9.5}
    p = B.plan(rows, dr, labels, fb, today="2026-10-23", low_fn=lambda t, since: lows.get(t))
    assert sorted(p["draw"]) == ["BOTBROKE", "NEW", "REJOLD"]
    assert sorted(p["obsolete"]["BOTBROKE"]) == ["4", "5"]
    assert p["skip"] == {"LINES": "his own Fib / horizontal lines (user-lines)", "NI": "not interesting", "STRUCT": "structure feedback < 8w", "BOTOK": "live bot drawing",
                         "REJ": "rejected under the current rule version"}
    # structure feedback expires after 8 weeks
    p2 = B.plan([dict(REP, ticker="STRUCT")], [], [], fb, today="2026-12-31", low_fn=lambda *a: None)
    assert p2["draw"] == ["STRUCT"]


def test_sql_insert_bot_is_active_with_meta():
    q = sql_insert_bot_drawing("abc", "long", entry=10, stop=9, target=13, t_start="2026-10-26", t_end="2027-03-15",
                               note="BOT", meta={"rule_version": "v", "why": {"a": "it's"}})
    assert "'bot'" in q and "'active'" in q and "'2027-03-15'" in q
    assert q.count("::jsonb") == 1 and "it''s" in q and q.startswith("insert into public.drawings (ticker")


def test_bot_rows_count_by_default():
    from srs_app.app_drawings import build_store
    from report_filters import drawing_source
    rows = [
        {"id": "z", "ticker": "AAA", "kind": "zone", "zone_top": 11, "zone_bottom": 10, "source": "bot", "status": "active"},
        {"id": "l", "ticker": "AAA", "kind": "long", "entry": 10.9, "stop": 9.9, "target": 14, "source": "bot", "status": "active"},
        {"id": "r", "ticker": "BBB", "kind": "zone", "zone_top": 5, "zone_bottom": 4, "source": "bot", "status": "rejected"},
        {"id": "u", "ticker": "CCC", "kind": "zone", "zone_top": 5, "zone_bottom": 4, "source": "user", "status": "active"},
    ]
    st = build_store(rows)
    assert st["AAA"]["source_override"] == "user" and st["AAA"]["bot_drawn"] is True and st["AAA"]["rr"] == 3.1
    assert "BBB" not in st  # rejected (negative feedback) never counts
    assert "bot_drawn" not in st["CCC"]
    src = drawing_source("AAA", st["AAA"], registry={}, approved={})
    assert src["tv_source"] == "bot-approved" and src["f_bot_review"] is False
