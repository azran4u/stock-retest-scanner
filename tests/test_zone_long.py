"""Bot Long follows the zone (Eyal 2026-10-23): srs_app.bot_drawings.long_from_zone on frozen daily bars must keep
reproducing tests/golden/zone_long_golden.json.gz, and the TS mirror (webapp/src/botlong.ts) must agree with it."""
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from srs_app import bot_drawings as B

ROOT = Path(__file__).resolve().parents[1]
G = json.loads(gzip.decompress((ROOT / "tests" / "golden" / "zone_long_golden.json.gz").read_bytes()))


@pytest.fixture(scope="module")
def rules(tmp_path_factory):
    H = {t: pd.DataFrame(rows, columns=["date", "Open", "High", "Low", "Close", "Volume"])
         .assign(date=lambda d: pd.to_datetime(d["date"])).set_index("date") for t, rows in G["daily"].items()}
    pk = tmp_path_factory.mktemp("hist") / "hist.pkl"
    pd.to_pickle(H, pk)
    saved = {k: os.environ.get(k) for k in ("SRS_HIST_CACHE", "SRS_TV_DRAWINGS")}
    os.environ.update(SRS_HIST_CACHE=str(pk), SRS_TV_DRAWINGS=str(ROOT / "tests" / "golden" / "tv_drawings_min.json"))
    mods = {m: sys.modules.pop(m) for m in ("infer", "infer_v2", "infer_v3", "infer_v3d") if m in sys.modules}
    old_dir, old_r = B.LEARN_DIR, dict(B._R)
    B.LEARN_DIR = Path(B.__file__).resolve().parent / "v3d"
    B._R.clear()
    yield B
    B._R.clear(); B._R.update(old_r); B.LEARN_DIR = old_dir
    for m in ("infer", "infer_v2", "infer_v3", "infer_v3d"):
        sys.modules.pop(m, None)
    sys.modules.update(mods)
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.mark.parametrize("c", G["cases"], ids=[f"{c['ticker']}-{c['variant']}" for c in G["cases"]])
def test_python_rule_matches_golden(c, rules):
    r = rules.long_from_zone(c["ticker"], c["zone_bottom"], c["zone_top"])
    assert abs(r["entry"] - c["entry"]) < 0.011 and abs(r["stop"] - c["stop"]) < 0.011 and r["sl_src"] == c["sl_src"], (r, c)


def test_golden_covers_both_sl_branches():
    srcs = {c["sl_src"] for c in G["cases"]}
    assert srcs == {"wick_low", "default_1atr"}


def test_ts_mirror_agrees_with_python():
    web = ROOT / "webapp"
    if not shutil.which("node") or not (web / "node_modules" / "esbuild").exists():
        pytest.skip("node / webapp node_modules not installed")
    p = subprocess.run(["node", "test_botlong.mjs"], cwd=web, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    assert f"{len(G['cases'])}/{len(G['cases'])} golden cases agree" in p.stdout
