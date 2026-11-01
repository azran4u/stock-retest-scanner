"""Expert zone (srs_app/expert_zone.py, Eyal 2026-11-01): base-top level of the last breakout, zone wick -> body,
validity checks, transparent 0-100 score. Synthetic weekly paths -> one daily bar per weekday."""
import json
from datetime import date, timedelta

from srs_app import expert_zone as E


def daily(weeks, start=date(2023, 1, 2), vol=None):
    """weeks = [(open, high, low, close)] -> Mon..Fri daily rows; Mon opens, Tue high, Wed low, Fri closes."""
    rows, d = [], start
    for i, (o, h, l, c) in enumerate(weeks):
        v = (vol[i] if vol else 1000) / 5
        m = (o + c) / 2
        for k in range(5):
            day = d + timedelta(days=k)
            oo = o if k == 0 else m
            cc = c if k == 4 else m
            hh = h if k == 1 else max(oo, cc)
            ll = l if k == 2 else min(oo, cc)
            rows.append([day.isoformat(), oo, hh, ll, cc, v])
        d += timedelta(days=7)
    return rows


def rally(n, a, b):
    """n weeks drifting from a to b, 2-point ranges (ATR ~ 2-3)."""
    out = []
    for i in range(n):
        c = a + (b - a) * (i + 1) / n
        o = a + (b - a) * i / n
        out.append((o, max(o, c) + 1, min(o, c) - 1, c))
    return out


def base_path(pull_to=101.0, after=None):
    """uptrend -> 12-week base under 100 (top 100 twice) -> breakout close 104 -> run to 115 -> pullback to pull_to."""
    w = rally(30, 60, 92)
    base = [(92, 100, 91, 97), (97, 99, 93, 94), (94, 97, 92, 95), (95, 98, 93, 96), (96, 100, 94, 98),
            (98, 99, 95, 96), (96, 98, 93, 95), (95, 97, 92, 96), (96, 98.5, 94, 97), (97, 99, 95, 98),
            (98, 99.2, 96, 98.5), (98.5, 99.5, 97, 99)]
    bo = [(99, 105, 98.5, 104)]
    run = rally(5, 104, 115)
    pb = rally(4, 115, pull_to)
    return w + base + bo + run + pb + (after or [])


def test_zone_is_base_top_wick_to_body():
    rows = daily(base_path())
    r = E.find(rows)
    assert r["ok"], r
    assert r["top"] == 100.0                      # highest wick of the base
    assert r["bottom"] < r["top"]
    A = r["atr_w"]
    assert 0.25 * A - 1e-6 <= r["top"] - r["bottom"] <= 0.5 * A + 1e-6   # width sanity
    assert r["breakout_week"] == (date(2023, 1, 2) + timedelta(weeks=42)).isoformat()
    assert 0 <= r["score"] <= 100
    assert r["score"] == round(sum(f["pts"] for f in r["factors"]))
    assert {f["k"] for f in r["factors"]} == {"time", "touches", "volume", "breakout", "retest", "recency", "round", "gap", "below", "confluence"}
    assert sum(f["max"] for f in r["factors"]) == 100
    assert all(f["src"] for f in r["factors"])
    t = {f["k"]: f for f in r["factors"]}
    n = int(t["touches"]["val"])
    assert n >= 2 and t["touches"]["pts"] == (15 if n >= 3 else 10)     # top visited more than once (separate runs)
    assert t["round"]["pts"] == 5                                         # 100 is round
    assert t["retest"]["val"] == "#1"


def test_broken_level_gives_no_expert_level():
    rows = daily(base_path(pull_to=90.0))   # weekly closes > 3% under the zone
    r = E.find(rows)
    assert not r["ok"] and "broken" in r["reason"]


def test_no_pullback_yet():
    path = base_path()[:-4] + rally(2, 115, 116)
    r = E.find(daily(path))
    assert not r["ok"] and "no pullback" in r["reason"]


def test_never_moved_away():
    w = rally(30, 60, 92)
    base = [(92, 100, 91, 97)] + [(97, 99, 93, 96)] * 8
    path = w + base + [(96, 101, 95, 100.5), (100.5, 101, 99, 100)]
    r = E.find(daily(path))
    assert not r["ok"]


def test_breakout_volume_counts_in_score():
    p = base_path()
    v = [1000] * len(p)
    v[42] = 3000                                    # breakout week 3x the 10-week average
    r = E.find(daily(p, vol=v))
    b = {f["k"]: f for f in r["factors"]}["breakout"]
    assert b["pts"] >= 10 and "x3.00" in b["val"]


def test_running_week_not_used_for_structure():
    rows = daily(base_path())
    rows = rows[:-2]                                  # last week ends on a Wednesday -> partial
    assert not E.week_complete(rows[-1][0])
    r = E.find(rows)
    assert r["ok"] and r["top"] == 100.0


def test_overlap_and_round_step():
    assert E.overlap(10, 9, 9.5, 8) is True
    assert E.overlap(10, 9, 8.9, 8) is False
    assert E.overlap(10, 9, None, None) is None
    assert E.round_step(12) == 1 and E.round_step(60) == 5 and E.round_step(300) == 10 and E.round_step(700) == 50


def test_build_writes_only_requested(tmp_path):
    (tmp_path / "candles").mkdir()
    (tmp_path / "candles" / "AAA.json").write_text(json.dumps({"d": daily(base_path())}))
    p = E.write(["AAA", "ZZZ"], tmp_path)
    doc = json.loads(p.read_text())
    assert doc["rule_version"] == E.RULE_VERSION
    assert set(doc["tickers"]) == {"AAA", "ZZZ"}
    assert doc["tickers"]["AAA"]["ok"] and doc["tickers"]["ZZZ"] == {"ok": False, "reason": "no candles"}
    assert E.refresh(tmp_path) == p and set(json.loads(p.read_text())["tickers"]) == {"AAA", "ZZZ"}


def test_follows_the_starred_list(tmp_path, monkeypatch):
    (tmp_path / "candles").mkdir()
    for t in ("AAA", "BBB", "CCC"):
        (tmp_path / "candles" / f"{t}.json").write_text(json.dumps({"d": daily(base_path())}))
    st = tmp_path / "app_state.json"
    st.write_text(json.dumps({"watchlist": ["AAA", "BBB"]}))
    p = E.sync_starred(tmp_path, state_path=str(st))
    assert set(json.loads(p.read_text())["tickers"]) == {"AAA", "BBB"}
    st.write_text(json.dumps({"watchlist": ["BBB", "CCC"]}))          # AAA unstarred, CCC starred
    E.sync_starred(tmp_path, state_path=str(st))
    assert set(json.loads(p.read_text())["tickers"]) == {"BBB", "CCC"}
    st.write_text(json.dumps({}))                                      # no list synced -> keep the file's set
    E.sync_starred(tmp_path, state_path=str(st))
    assert set(json.loads(p.read_text())["tickers"]) == {"BBB", "CCC"}


def test_add_and_remove_merge(tmp_path, monkeypatch):
    (tmp_path / "candles").mkdir()
    (tmp_path / "candles" / "AAA.json").write_text(json.dumps({"d": daily(base_path())}))
    E.write(["AAA"], tmp_path)
    monkeypatch.setattr(E, "_yf_rows", lambda t: daily(base_path()) if t == "NEW" else None)
    p = E.add(["new"], tmp_path)
    doc = json.loads(p.read_text())["tickers"]
    assert set(doc) == {"AAA", "NEW"} and doc["NEW"]["ok"]            # no app candles -> downloaded in memory
    assert not (tmp_path / "candles" / "NEW.json").exists()
    E.remove(["AAA"], tmp_path)
    assert set(json.loads(p.read_text())["tickers"]) == {"NEW"}


def test_kbwb_five_closes_under_the_zone_is_broken():
    """Regression (Eyal 2026-11-01): KBWB closed under its expert-zone bottom 89.02 for 5 straight weeks (lows 86.78)
    and stayed valid with score 82 under v1. Two consecutive closes under the bottom now break it: no expert level at
    89.02-89.94 (an older valid level is allowed)."""
    from pathlib import Path
    rows = json.loads((Path(__file__).parent / "data" / "kbwb_daily_20261030.json").read_text())["d"]
    r = E.find(rows, asof="2026-11-01")
    assert not (r["ok"] and r["bottom"] == 89.02 and r["top"] == 89.94), r
    if r["ok"]:
        assert r["top"] < 89.02


def _with_closes_below(n_below):
    """base_path pulled back into the zone, then n_below weekly closes under the zone bottom, then back inside."""
    p = base_path(pull_to=100.5)
    r0 = E.find(daily(p))
    bot = r0["bottom"]
    under = [(bot + 0.2, bot + 0.3, bot - 1.2, bot - 0.4)] * n_below
    back = [(bot - 0.4, r0["top"] + 0.2, bot - 0.5, bot + 0.3)]
    return E.find(daily(p + under + back)), r0


def test_single_close_below_is_flagged_with_penalty():
    r, r0 = _with_closes_below(1)
    assert r["ok"] and r["top"] == r0["top"]
    assert len(r["warnings"]) == 1 and r["warnings"][0]["he"].startswith("סגירה שבועית מתחת לאזור")
    below = {f["k"]: f for f in r["factors"]}["below"]
    assert below["pts"] == -10 and below["val"] == r["warnings"][0]["date"]


def test_two_consecutive_closes_below_break_the_level():
    r, r0 = _with_closes_below(2)
    assert not (r["ok"] and r["top"] == r0["top"])
    if not r["ok"]:
        assert "broken" in r["reason"]
