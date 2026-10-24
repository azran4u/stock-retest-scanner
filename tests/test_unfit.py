"""'לא מתאימה לשיטה' (merged not-interesting + not-technical, 2026-10-24): label not_interesting with until + note."""
from srs_app import sync


ROWS = [
    {"ticker": "aaa", "value": "yes", "until": "2026-12-19", "note": "unfit: range for 3y", "asof": "2026-10-24"},
    {"ticker": "BBB", "value": "yes", "until": "2026-11-01", "note": "unfit", "asof": "2026-10-04"},
    {"ticker": "CCC", "value": "yes", "until": "2026-10-01", "note": "unfit", "asof": "2026-08-01"},   # expired -> back
    {"ticker": "DDD", "value": "no", "until": None, "note": None, "asof": "2026-10-20"},               # returned now
    {"ticker": "EEE", "value": "yes", "until": None, "note": None, "asof": "2026-09-01"},              # old-style mark
]


def test_nightly_exclusion_unchanged():
    assert sync.not_interesting_active(ROWS, "2026-10-24") == {"AAA": "2026-12-19", "BBB": "2026-11-01", "EEE": None}


def test_unfit_marks_are_both_verdicts():
    m = sync.unfit_marks(ROWS, "2026-10-24")
    assert set(m) == {"AAA", "BBB", "EEE"}
    assert m["AAA"] == {"until": "2026-12-19", "reason": "range for 3y", "merged": True, "asof": "2026-10-24"}
    assert m["BBB"]["merged"] and m["BBB"]["reason"] is None
    assert m["EEE"]["merged"] is False
    assert "CCC" not in sync.unfit_marks(ROWS, "2026-10-24")      # expired: returns automatically
    assert "BBB" not in sync.unfit_marks(ROWS, "2026-11-02")
