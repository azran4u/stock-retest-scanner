"""Expert zones are THE zone / Long (Eyal 2026-11-02): srs_app.expert_drawings.plan / emit_sql."""
from srs_app import expert_drawings as X
from srs_app import bot_drawings as B

Z = {"rule_version": "expert-v7-2026-11-01", "tickers": {
    "NEW": {"ok": True, "top": 10.0, "bottom": 9.5, "pivot_week": "2026-05-04", "breakout_week": "2026-06-01", "last_week": "2026-10-26",
            "atr_w": 1.0, "trade": {"entry": 10.0, "sl": 9.0, "tp": 13.0, "rr": 3.0}},
    "SAME": {"ok": True, "top": 20.0, "bottom": 19.0, "pivot_week": "2026-05-04", "last_week": "2026-10-26", "atr_w": 1,
             "trade": {"entry": 20.0, "sl": 18.0, "tp": 26.0, "rr": 3.0}},
    "MINE": {"ok": True, "top": 30.0, "bottom": 29.0, "last_week": "2026-10-26", "atr_w": 1, "trade": {"entry": 30.0, "sl": 28.0, "tp": 36.0}},
    "GONE": {"ok": False, "reason": "broken"},
}}
D = [
    {"id": "o1", "ticker": "NEW", "kind": "zone", "source": "bot", "status": "active", "meta": {"rule_version": "v5-2026-10-26"}},
    {"id": "o2", "ticker": "NEW", "kind": "long", "source": "bot", "status": "active", "meta": {"rule_version": "v5-2026-10-26"}},
    {"id": "e1", "ticker": "SAME", "kind": "zone", "source": "bot", "status": "active", "zone_top": 20, "zone_bottom": 19, "meta": {"expert": True}},
    {"id": "e2", "ticker": "SAME", "kind": "long", "source": "bot", "status": "active", "entry": 20, "stop": 18, "target": 26, "meta": {"expert": True}},
    {"id": "u1", "ticker": "MINE", "kind": "zone", "source": "user", "status": "active", "zone_top": 31, "zone_bottom": 30},
    {"id": "t1", "ticker": "MINE", "kind": "long", "source": "tv", "status": "active", "entry": 31, "stop": 29, "target": 35},
    {"id": "b9", "ticker": "MINE", "kind": "zone", "source": "bot", "status": "active", "meta": {"rule_version": "v5"}},
    {"id": "g1", "ticker": "GONE", "kind": "zone", "source": "bot", "status": "active", "meta": {"expert": True}},
    {"id": "r1", "ticker": "OLD", "kind": "zone", "source": "bot", "status": "rejected", "meta": {"rule_version": "v3d"}},
]


def test_plan_expert_primary_his_override_and_retire(tmp_path):
    pl = X.plan(D, Z)
    assert [lv["ticker"] for lv in pl["insert"]] == ["NEW"] and pl["keep"] == ["SAME"] and pl["his"] == ["MINE"]
    assert {t: sorted(d["id"] for d in rs) for t, rs in pl["retire"].items()} == {"NEW": ["o1", "o2"], "MINE": ["b9"], "GONE": ["g1"]}
    assert pl["none"] == ["GONE"]
    lv = pl["insert"][0]
    assert (lv["entry"], lv["stop"], lv["target"], lv["t_start"], lv["t_end"]) == (10.0, 9.0, 13.0, "2026-11-02", "2027-03-22")
    sql = X.emit_sql(pl)
    assert not any("'u1'" in s or "'t1'" in s for s in sql)                       # his rows are never touched
    assert all("source = 'bot'" in s for s in sql if s.startswith("update"))
    assert sum(s.startswith("insert") for s in sql) == 2 and '"expert":true' in sql[-1]
    p = X.backup(pl, "2026-11-02", tmp_path)
    assert p and len(__import__("json").loads(p.read_text())["rows"]) == 4


def test_bot_pipeline_routes_to_expert_and_never_redraws_his():
    assert B.EXPERT_MODE is True and B.REDRAW_BROKEN_USER is False
