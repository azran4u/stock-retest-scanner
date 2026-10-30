"""Upload the web app's data (app/data/**.json) to Supabase Storage (PRIVATE bucket 'app-data', Eyal 2026-10-30).

The app reads its data only after his login (storage policy: owner email); nothing is published on a public site.
Upload goes through the edge function `srs-data-upload` with a nightly token (header x-srs-token; the box keeps the
token in /workspace/.secrets/srs_upload_token, Supabase keeps only its SHA-256). Only files whose content changed since
the last successful upload are sent (manifest /workspace/cache/app_data_uploaded.json); candle files that are no longer
exported are deleted from the bucket.

  python -m srs_app.publish_data            # upload changed files
  python -m srs_app.publish_data --all      # re-upload everything
  python -m srs_app.publish_data --check    # dry run: what would be uploaded
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

FUNC_URL = os.environ.get("SRS_UPLOAD_URL", "https://wkkdblnykgolqijzagva.supabase.co/functions/v1/srs-data-upload")
TOKEN_FILE = Path(os.environ.get("SRS_UPLOAD_TOKEN_FILE", "/workspace/.secrets/srs_upload_token"))
MANIFEST = Path(os.environ.get("SRS_UPLOAD_MANIFEST", "/workspace/cache/app_data_uploaded.json"))
BATCH_BYTES = 3_000_000


def token() -> str | None:
    t = os.environ.get("SRS_UPLOAD_TOKEN")
    if t:
        return t.strip()
    try:
        return TOKEN_FILE.read_text().strip() or None
    except OSError:
        return None


def scan(data_dir: Path) -> dict[str, tuple[str, Path]]:
    """relative path -> (sha256, file) for every .json under data_dir"""
    out = {}
    for p in sorted(data_dir.rglob("*.json")):
        rel = p.relative_to(data_dir).as_posix()
        out[rel] = (hashlib.sha256(p.read_bytes()).hexdigest(), p)
    return out


def plan(files: dict[str, tuple[str, Path]], manifest: dict[str, str], all_: bool = False) -> tuple[list[str], list[str]]:
    """(paths to upload, paths to delete). Deletes only candle files that the export no longer writes."""
    up = [k for k, (h, _) in files.items() if all_ or manifest.get(k) != h]
    gone = [k for k in manifest if k not in files and k.startswith("candles/")]
    return up, gone


def batches(paths: list[str], files: dict[str, tuple[str, Path]], limit: int = BATCH_BYTES):
    cur, size = [], 0
    for k in paths:
        n = files[k][1].stat().st_size
        if cur and size + n > limit:
            yield cur
            cur, size = [], 0
        cur.append(k)
        size += n
    if cur:
        yield cur


def post(body: dict, tok: str, url: str = FUNC_URL, tries: int = 3) -> dict:
    data = json.dumps(body).encode()
    for i in range(tries):
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", "x-srs-token": tok})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 207:
                return json.loads(e.read() or b"{}")
            if e.code in (401, 403, 400) or i == tries - 1:
                raise RuntimeError(f"upload HTTP {e.code}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise RuntimeError(f"upload failed: {e}") from e
        time.sleep(2 * (i + 1))
    return {}


def publish(data_dir: Path, all_: bool = False, check: bool = False, quiet: bool = False) -> dict:
    tok = token()
    if not tok:
        raise RuntimeError(f"no upload token ({TOKEN_FILE} / SRS_UPLOAD_TOKEN)")
    files = scan(data_dir)
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        manifest = {}
    up, gone = plan(files, manifest, all_)
    res = {"files": len(files), "changed": len(up), "deleted": 0, "uploaded": 0, "failed": []}
    if check:
        res["would_upload"] = up[:50]
        res["would_delete"] = gone
        return res
    for b in batches(up, files):
        r = post({"files": [{"path": k, "content": files[k][1].read_text()} for k in b]}, tok)
        bad = {f.get("path") for f in r.get("failed", [])}
        res["failed"] += r.get("failed", [])
        for k in b:
            if k not in bad:
                manifest[k] = files[k][0]
        res["uploaded"] += int(r.get("uploaded", 0))
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifest))
        if not quiet:
            print(f"  [app data upload] {res['uploaded']}/{len(up)}", flush=True)
    if gone:
        r = post({"delete": gone}, tok)
        res["deleted"] = int(r.get("deleted", 0))
        for k in gone:
            manifest.pop(k, None)
        MANIFEST.write_text(json.dumps(manifest))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent.parent / "app" / "data"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    r = publish(Path(a.data), a.all, a.check)
    print(json.dumps(r, ensure_ascii=False))
    if r.get("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
