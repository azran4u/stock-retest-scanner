"""srs_app.publish_data: only changed files are uploaded, stale candle files deleted, batches stay under the limit."""
from pathlib import Path

from srs_app import publish_data as pd_


def _files(tmp: Path, spec: dict[str, str]):
    for k, v in spec.items():
        p = tmp / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(v)
    return pd_.scan(tmp)


def test_plan_changed_and_deleted(tmp_path):
    f = _files(tmp_path, {"index.json": "{}", "candles/A.json": "[1]", "candles/B.json": "[2]"})
    man = {"index.json": f["index.json"][0], "candles/A.json": "old", "candles/Z.json": "x", "rules.json": "y"}
    up, gone = pd_.plan(f, man)
    assert sorted(up) == ["candles/A.json", "candles/B.json"]
    assert gone == ["candles/Z.json"]  # only candle files are removed; other names are left alone
    up_all, _ = pd_.plan(f, man, all_=True)
    assert len(up_all) == 3


def test_batches_respect_limit(tmp_path):
    f = _files(tmp_path, {f"candles/T{i}.json": "x" * 400 for i in range(10)})
    bs = list(pd_.batches(sorted(f), f, limit=1000))
    assert sum(len(b) for b in bs) == 10 and all(len(b) <= 2 for b in bs)


def test_no_token_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("SRS_UPLOAD_TOKEN", raising=False)
    monkeypatch.setattr(pd_, "TOKEN_FILE", tmp_path / "none")
    try:
        pd_.publish(tmp_path)
    except RuntimeError as e:
        assert "token" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
