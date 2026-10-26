"""Nightly-path guard (2026-10-26): every default drawing lookup (screen R:R gate, report_filters recompute,
tv_drawings merge) uses the web app store app_drawings.json when present, like export_daily_report - a recompute
with the legacy TradingView store dropped PASS 77 -> 16. SRS_DRAWING_STORE=tv forces the legacy store."""
import json

import stock_screen as ss
from srs_app.app_drawings import load_rows


def _stores(tmp_path, monkeypatch):
    app, tv = tmp_path / "app.json", tmp_path / "tv.json"
    app.write_text(json.dumps({"AAA": {"found": True, "rr": 3.0, "source": "bot"}}))
    tv.write_text(json.dumps({"AAA": {"found": False}}))
    monkeypatch.setattr(ss, "APP_DRAWINGS_JSON", app)
    monkeypatch.setattr(ss, "TV_DRAWINGS_JSON", tv)
    ss._STORE_CACHE.clear()
    return app, tv


def test_default_store_is_app(tmp_path, monkeypatch):
    _stores(tmp_path, monkeypatch)
    monkeypatch.delenv("SRS_DRAWING_STORE", raising=False)
    assert ss.drawing_store()["AAA"]["found"] is True


def test_env_forces_tv_and_missing_app_falls_back(tmp_path, monkeypatch):
    app, _ = _stores(tmp_path, monkeypatch)
    monkeypatch.setenv("SRS_DRAWING_STORE", "tv")
    assert ss.drawing_store()["AAA"]["found"] is False
    monkeypatch.delenv("SRS_DRAWING_STORE")
    app.unlink(); ss._STORE_CACHE.clear()
    assert ss.drawing_store()["AAA"]["found"] is False


def test_report_filters_and_merge_default_to_drawing_store():
    import inspect
    import report_filters as rf
    import tv_drawings as T
    assert "ss.drawing_store()" in inspect.getsource(rf.apply_filters_to_report)
    assert "ss.drawing_store()" in inspect.getsource(T.merge_df)
    assert "drawing_store()" in inspect.getsource(ss._apply_tv_rr_gate)


def test_load_rows_accepts_text_wrapped_tool_output(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text('<cursor_untrusted_data_redacted source="x">\n\n{"result":"Below ... <untrusted-data-1>\\n[{\\"ticker\\":\\"MU\\"}]\\n</untrusted-data-1>"}\n\n</cursor_untrusted_data_redacted>')
    assert load_rows(p) == [{"ticker": "MU"}]
