"""Eyal 2026-10-26: the uptrend (f_technical) is re-evaluated every run; a manual verdict does not freeze it."""
from datetime import date

import report_filters as rf


def _with(monkeypatch, o):
    monkeypatch.setattr(rf, "load_user_overrides", lambda: {"XYZ": o})


def test_override_holds_one_week(monkeypatch):
    _with(monkeypatch, {"technical": False, "date": "2026-10-20"})
    r = rf.apply_user_overrides({"f_technical": True}, "XYZ", date(2026, 10, 26))
    assert r["f_technical"] is False and r["tech_computed"] is True and r["tech_override"]


def test_override_expires_after_a_week(monkeypatch):
    _with(monkeypatch, {"technical": False, "date": "2026-10-09"})
    r = rf.apply_user_overrides({"f_technical": True}, "XYZ", date(2026, 10, 26))
    assert r["f_technical"] is True and r["tech_override"] == ""
    assert rf.user_technical("XYZ", date(2026, 10, 26)) is None


def test_override_until_date(monkeypatch):
    _with(monkeypatch, {"technical": False, "date": "2026-10-01", "until": "2026-11-30"})
    assert rf.user_technical("XYZ", date(2026, 10, 26)) is False
    assert rf.user_technical("XYZ", date(2026, 12, 1)) is None


def test_undated_override_does_not_freeze(monkeypatch):
    _with(monkeypatch, {"technical": False})
    assert rf.user_technical("XYZ", date(2026, 10, 26)) is None
