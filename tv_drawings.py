#!/usr/bin/env python3
"""TradingView drawings store + report merge (read-only source of zone/entry/SL/TP/R:R).

The user's TradingView drawings are the source of truth for the trade levels:
a Rectangle = zone (top/bottom) and a Long Position tool = entry / stop / target
and TradingView's R:R. A browser agent READS them daily (never edits, moves or
deletes a drawing) and records the values here.

Store: /workspace/stock-screener/tv_drawings.json, keyed by ticker:
  {"ST": {"found": true, "zone_top": 41.96, "zone_bottom": 41.31, "entry": 42.11,
          "sl": 38.46, "tp": 51.55, "rr": 2.59, "read_at": "...", "read_date": "YYYY-MM-DD",
          "symbol": "NYSE:ST"}}

Daily target set = report rows passing f_dollar_vol AND f_short_float AND
f_no_earnings_14d (evaluated LIVE vs today from the cached earnings date, same as
the dashboard) AND f_history (no smooth-streak requirement: covers every stock that
could PASS or needs a drawing).

Usage:
  python tv_drawings.py targets [--report CSV] [--today YYYY-MM-DD]
        -> /workspace/tv_read_targets.txt (EXCHANGE:TICKER per line) + .json
  python tv_drawings.py upsert ST --zone-top 41.96 --zone-bottom 41.31 \\
        --entry 42.11 --sl 38.46 --tp 51.55 --rr 2.59 [--read-at ISO]
  python tv_drawings.py upsert XYZ --not-found
  python tv_drawings.py upsert NYSE:ST ...values... --screenshot /workspace/tv_shots/ST.png
        -> charts/latest/ST.webp in the repo (<=1280px, <300KB, overwritten) + store
           fields screenshot / screenshot_at / screenshot_date
  python tv_drawings.py screenshot NYSE:ST /workspace/tv_shots/ST.png   (image only)
  python tv_drawings.py merge [--report CSV ...] [--no-grok-target]
        -> writes tv_found, tv_zone_top, tv_zone_bottom, tv_entry, tv_sl, tv_tp, tv_rr,
           tv_read_date (latest stored reading per ticker) into latest.csv + its dated
           twin, sets f_rr = found AND tv_rr >= 2, recomputes status / failed_filters /
           reason, and regenerates /workspace/stock-screener/grok_sync_target.{json,txt}
  python tv_drawings.py stale [--no-refresh] [--as-of YYYY-MM-DD] [--ticker T] [--close-basis low|daily|weekly]
        -> flags found drawings that may be obsolete: broken (ANY price below the SL since the
           read date = a daily low < SL by default; --close-basis daily/weekly = daily/weekly
           closes; latest close < SL always), target hit (close >= TP), far (close > zone
           top + 3 weekly ATR(14)); refreshes cached prices of drawn tickers first;
           writes /workspace/stock-screener/tv_stale.{json,csv}
  python tv_drawings.py upsert NYSE:SSB ...values... [--source bot|user] [--label "BOT - review needed"]
        -> drawing source: bot drawings (registry match / --source bot / rectangle text
           "BOT - review needed") are "review needed" and never count toward f_rr / PASS /
           grok_sync_target until approved; changed levels vs the bot registry = user-owned
  python tv_drawings.py bot register [--csv /workspace/drawing-learn/bot_drawings.csv]
        -> /workspace/stock-screener/bot_drawings.json (levels the bot drew; no-level rows =
           "needs manual drawing (data issue)")
  python tv_drawings.py upsert NYSE:FIVE --entry .. --sl .. --tp .. --rr .. --partial --drawing-status "user drawing (no rectangle)"
  python tv_drawings.py upsert NYSE:J --not-found --lines-only   (user Fib / lines only: not needs drawing)
  python tv_drawings.py bot approve T [T ...] | bot unapprove T [T ...] | bot unregister T [T ...] | bot list | bot shots
        -> approved_bot_drawings.json (approved bot drawings count like the user's own);
           shots = attach new /workspace/tv_shots/<T>*.png images of bot drawings
  python tv_drawings.py show [TICKER]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

_HERE = Path(__file__).resolve().parent
for _d in (_HERE, Path("/workspace/publish-stock-retest-scanner"), Path("/workspace")):
    if str(_d) not in sys.path and (_d / "report_filters.py").exists():
        sys.path.insert(0, str(_d))
        break

STORE = Path("/workspace/stock-screener/tv_drawings.json")
REPO = Path("/workspace/publish-stock-retest-scanner")
LATEST = REPO / "historical-reports" / "latest.csv"
TARGETS_TXT = Path("/workspace/tv_read_targets.txt")
TARGETS_JSON = Path("/workspace/tv_read_targets.json")
GROK_TARGET_DIR = Path("/workspace/stock-screener")  # grok_sync_target.{json,txt}
# Chart screenshots: ONE current image per ticker, overwritten on each read (no history).
CHARTS_DIR = REPO / "charts" / "latest"
SHOT_MAX_WIDTH = 1280
SHOT_MAX_BYTES = 300_000
TZ = ZoneInfo("Asia/Jerusalem")

TARGET_FILTERS = ["f_dollar_vol", "f_short_float", "f_no_earnings_14d", "f_history"]
TV_COLS = ["tv_found", "tv_zone_top", "tv_zone_bottom", "tv_entry", "tv_sl", "tv_tp", "tv_rr", "tv_read_date",
           "tv_screenshot"]
EARNINGS_BLACKOUT_DAYS = 14  # same as stock_screen.EARNINGS_BLACKOUT_DAYS / dashboard
RR_MIN = 2.0  # same as stock_screen.RR_MIN / report_filters CONFIG["rr_min"]
try:
    import stock_screen as _ss  # noqa: E402

    RR_MIN = float(_ss.RR_MIN)
except Exception:
    pass


def _today() -> date:
    return datetime.now(TZ).date()


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def _symbol(row: pd.Series) -> str:
    m = re.search(r"symbol=([^&]+)", str(row.get("tradingview_url") or ""))
    return m.group(1) if m else str(row["ticker"]).upper().replace("-", ".")


def _earn_cached(ticker: str) -> Optional[str]:
    try:
        d = json.loads((Path("/workspace/cache") / f"earn_{ticker.strip().upper()}.json").read_text())
        return str(d.get("earnings_date") or "")[:10] or None
    except Exception:
        return None


def no_earnings_live(ticker: str, row_date: Any, today: date) -> bool:
    """Live f_no_earnings_14d: earliest known future date (earnings cache, then the
    report's earnings_date); unknown / already passed -> False."""
    for cand in (_earn_cached(ticker), row_date):
        if cand is None or str(cand).strip() in ("", "nan", "None"):
            continue
        try:
            d = date.fromisoformat(str(cand)[:10])
        except Exception:
            continue
        if d >= today:
            return (d - today).days >= EARNINGS_BLACKOUT_DAYS
    return False


def target_rows(df: pd.DataFrame, today: date) -> pd.DataFrame:
    live = df.apply(lambda r: no_earnings_live(str(r["ticker"]), r.get("earnings_date"), today), axis=1)
    mask = live.astype(bool)
    for f in TARGET_FILTERS:
        if f == "f_no_earnings_14d":
            continue
        mask &= df[f].map(_truthy)
    out = df[mask].copy()
    out["tv_symbol"] = out.apply(_symbol, axis=1)
    return out


def load_store() -> Dict[str, Dict[str, Any]]:
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return {}


def save_store(store: Dict[str, Dict[str, Any]]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(dict(sorted(store.items())), indent=2) + "\n")


def csv_ticker(ticker: str) -> str:
    """Store / CSV / filename spelling: 'NYSE:MOG.A' -> 'MOG-A'."""
    t = ticker.strip().upper()
    if ":" in t:
        t = t.split(":", 1)[1]
    return t.replace(".", "-")


def save_screenshot(ticker: str, src: Path) -> str:
    """Resize (<= SHOT_MAX_WIDTH px wide) + compress `src` into CHARTS_DIR/<TICKER>.webp
    (overwrites; removes any other-format copy of the same ticker). Returns the
    repo-relative path, e.g. 'charts/latest/MOG-A.webp'."""
    from PIL import Image

    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"screenshot not found: {src}")
    t = csv_ticker(ticker)
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = CHARTS_DIR / f"{t}.webp"
    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.width > SHOT_MAX_WIDTH:
            im = im.resize((SHOT_MAX_WIDTH, round(im.height * SHOT_MAX_WIDTH / im.width)), Image.LANCZOS)
        for q in (80, 70, 60, 50, 40):
            im.save(dest, "WEBP", quality=q, method=6)
            if dest.stat().st_size <= SHOT_MAX_BYTES:
                break
        while dest.stat().st_size > SHOT_MAX_BYTES and im.width > 640:
            im = im.resize((int(im.width * 0.85), int(im.height * 0.85)), Image.LANCZOS)
            im.save(dest, "WEBP", quality=50, method=6)
    for old in CHARTS_DIR.glob(f"{t}.*"):
        if old != dest:
            old.unlink()
    return dest.relative_to(REPO).as_posix()


def remove_screenshot(ticker: str) -> None:
    for old in CHARTS_DIR.glob(f"{csv_ticker(ticker)}.*"):
        old.unlink()


def upsert(ticker: str, found: bool, symbol: Optional[str] = None, read_at: Optional[str] = None,
           screenshot: Optional[Path] = None, source: Optional[str] = None, label: Optional[str] = None,
           lines_only: bool = False, drawing_status: Optional[str] = None, drawing_note: Optional[str] = None,
           **vals: Optional[float]) -> Dict[str, Any]:
    t = ticker.strip().upper()
    if ":" in t:
        symbol = t
    t = csv_ticker(t)
    ts = datetime.fromisoformat(read_at) if read_at else datetime.now(TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=TZ)
    rec: Dict[str, Any] = {"found": bool(found)}
    for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr"):
        rec[k] = (float(vals[k]) if vals.get(k) is not None else None) if found else None
    rec["read_at"] = ts.isoformat(timespec="seconds")
    rec["read_date"] = ts.astimezone(TZ).date().isoformat()
    if symbol:
        rec["symbol"] = symbol
    store = load_store()
    prev = store.get(t) or {}
    if label:
        rec["label"] = label
    if lines_only and not found:
        rec["lines_only"] = True
    elif not found and not lines_only and prev.get("lines_only") and drawing_status is None:
        # a later "not found" read of a lines-only chart stays lines-only (no zone / position)
        rec["lines_only"] = True
        drawing_note = drawing_note or prev.get("drawing_note")
    if drawing_status:
        rec["drawing_status"] = drawing_status
    if drawing_note:
        rec["drawing_note"] = drawing_note
    _resolve_upsert_source(t, rec, prev, source, label)
    # every read gets a screenshot, found or not (not-found charts show as "needs drawing" cards)
    if screenshot is not None:
        rec["screenshot"] = save_screenshot(t, screenshot)
        rec["screenshot_at"] = rec["read_at"]
        rec["screenshot_date"] = rec["read_date"]
    elif prev.get("screenshot") and (REPO / prev["screenshot"]).exists():
        for k in ("screenshot", "screenshot_at", "screenshot_date"):  # keep the last image
            if k in prev:
                rec[k] = prev[k]
    store[t] = rec
    save_store(store)
    return rec


def _resolve_upsert_source(t: str, rec: Dict[str, Any], prev: Dict[str, Any],
                           source: Optional[str], label: Optional[str]) -> None:
    """Set rec['source_override'] / rec['source'] for a new read (see report_filters.drawing_source).

    --source bot: the bot drew these levels -> (re)register them in bot_drawings.json.
    --label with "BOT ... review": bot only if the levels still match the registry (or there is
    no registry entry -> registered now); changed levels = the user edited it = user-owned.
    --source user: user-owned regardless of the registry (kept on later reads while the levels
    are unchanged)."""
    import report_filters as rf

    reg = dict(rf.load_bot_registry())
    b = reg.get(t)
    label_bot = bool(label and rf.BOT_LABEL_RE.search(label))
    if source == "user":
        rec["source_override"] = "user"
    elif rec.get("found") and (source == "bot" or (label_bot and not b)):
        rec["source_override"] = "bot"
        if not b or not rf.levels_match(rec, b):
            bot_register_levels(t, rec, note="registered by upsert --source bot" if source == "bot"
                                else "registered from rectangle text 'BOT - review needed'")
    elif prev.get("source_override") == "user" and rf.levels_match(prev, rec):
        rec["source_override"] = "user"
    rec["source"] = rf.drawing_source(t, rec)["tv_source"] or ("user" if rec.get("found") else "")


def _hist_upto(hist_map: Dict[str, Any], ticker: str, report_date: Optional[date]) -> Optional[pd.DataFrame]:
    """Cached daily OHLCV for `ticker` cut at report_date (same prep as report_filters)."""
    import stock_screen as ss

    raw = hist_map.get(ticker) if hist_map else None
    need = ["Open", "High", "Low", "Close", "Volume"]
    if raw is None or getattr(raw, "empty", True):
        return None
    try:
        d = ss._normalize_ohlcv_index(raw)
        if not all(c in d.columns for c in need):
            return None
        if report_date is not None:
            d = d[d.index.normalize() <= pd.Timestamp(report_date)]
        d = d[need].dropna()
        return d if len(d) else None
    except Exception:
        return None


def _csv_val(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


def merge_df(df: pd.DataFrame, today: Optional[date] = None,
             store: Optional[Dict[str, Dict[str, Any]]] = None,
             report_date: Optional[date] = None,
             hist_map: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Apply the store to a report frame and recompute status.

    tv_* = the latest stored reading for each ticker (any ticker with a reading;
    tv_found yes / no, '' = never read). f_rr = found AND tv_rr >= rr_min, then
    status / failed_filters / reason are recomputed from the core filters
    (report_filters.finalize_status / status_reason). `today` is unused (kept for
    backwards-compatible calls). Also refreshes the price-vs-zone columns
    (tv_price, tv_weekly_atr, tv_zone_dist, tv_zone_dist_atr, f_near_zone) from the
    cached daily history (`hist_map`, default /workspace/hist_cache.pkl) as of
    `report_date` (default: the report's own date column is absent -> today).
    """
    import report_filters as rf
    import stock_screen as ss

    if hist_map is None:
        hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    report_date = report_date or _today()

    store = load_store() if store is None else store
    store = {str(k).strip().upper(): v for k, v in store.items()}
    df = df.copy()
    if "f_rr_computed" not in df.columns:  # pre-TV report: old f_rr was the computed flag
        df["f_rr_computed"] = df["f_rr"] if "f_rr" in df.columns else False
    for c in TV_COLS + rf.NEAR_ZONE_COLS + rf.INFO_FILTERS + rf.STALE_COLS + rf.SOURCE_COLS + rf.TECH_COLS + rf.EVIDENCE_COLS:
        df[c] = pd.Series([""] * len(df), index=df.index, dtype=object)
    for c in rf.REVERSAL_COLS:
        if c in df.columns:
            df[c] = df[c].astype(object).where(df[c].notna(), "")
    for c in ("f_rr", "status", "failed_filters", "reason", "needs_drawing"):
        df[c] = df[c].astype(object) if c in df.columns else pd.Series([""] * len(df), index=df.index, dtype=object)
    for i, row in df.iterrows():
        r = {k: row[k] for k in df.columns}
        rec = store.get(str(row["ticker"]).strip().upper())
        rf.apply_tv(r, rec)
        rf.apply_source(r, str(row["ticker"]).strip(), rec)
        rf.finalize_status(r)
        reason = rf.status_reason(r, row.get("reason"))
        for c in TV_COLS + ["f_rr", "status", "failed_filters"]:
            df.at[i, c] = r[c]
        for c in rf.SOURCE_COLS:
            df.at[i, c] = _csv_val(r[c])
        df.at[i, "needs_drawing"] = _csv_val(rf.compute_needs_drawing(r))
        h = _hist_upto(hist_map, str(row["ticker"]).strip(), report_date)
        nz = rf.compute_near_zone(h, r)
        for c, v in nz.items():
            df.at[i, c] = _csv_val(v)
        st = rf.compute_stale(h, r)
        for c in rf.STALE_COLS:
            df.at[i, c] = _csv_val(st[c])
        tech = rf.apply_user_overrides(dict(rf.compute_technical(h), ticker=str(row["ticker"]).strip()),
                                       str(row["ticker"]).strip())
        for c in rf.TECH_COLS:
            df.at[i, c] = _csv_val(tech.get(c))
        for c, v in rf.compute_evidence(h, r).items():  # reversal evidence (grade inputs)
            df.at[i, c] = _csv_val(v)
        if h is not None and len(h) >= 2 and "f_weekly_reversal" in df.columns:
            # E1/E2 reversal candles count only at the TV zone -> refresh with the merged zone
            for c, v in rf.compute_reversals(h, report_date, r).items():
                df.at[i, c] = _csv_val(v) if isinstance(v, bool) else v
        notes = [n for n in str(row.get("filter_notes") or "").split("; ")
                 if n and "(f_rr False" not in n]  # incl. "(f_rr False until approved)" (bot drawings)
        if not r["f_rr"]:
            notes.append(rf.tv_note(r))
        if "filter_notes" in df.columns:
            df.at[i, "filter_notes"] = "; ".join(notes)
        df.at[i, "reason"] = reason
    return place_tv_cols(df)


def place_tv_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Column order = report_filters.REPORT_COLS for known columns, extras kept after."""
    import report_filters as rf

    known = [c for c in rf.REPORT_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in rf.REPORT_COLS]
    return df[known + extra]


def _default_reports() -> List[Path]:
    """latest.csv plus the dated CSV that is byte-identical to it (the day's twin)."""
    out = [LATEST]
    if LATEST.exists():
        data = LATEST.read_bytes()
        for p in sorted(LATEST.parent.glob("????-??-??.csv"), reverse=True):
            if p.read_bytes() == data:
                out.append(p)
                break
    return out


def _report_date(paths: List[Path]) -> str:
    for p in paths:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem):
            return p.stem
    return _today().isoformat()


STALE_JSON = GROK_TARGET_DIR / "tv_stale.json"
STALE_CSV = GROK_TARGET_DIR / "tv_stale.csv"
STALE_FIELDS = ["ticker", "symbol", "flag", "detail", "zone_bottom", "zone_top", "sl", "tp", "rr",
                "latest_close", "last_bar", "weekly_atr", "dist_above_top_atr", "read_date"]


def _rec_as_row(t: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    r = {"ticker": t, "tv_found": "yes" if rec.get("found") else "no", "tv_read_date": rec.get("read_date") or ""}
    for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr"):
        r[f"tv_{k}"] = rec.get(k)
    return r


def stale_check(tickers: Optional[List[str]] = None, as_of: Optional[date] = None, refresh: bool = True,
                write: bool = True, quiet: bool = False) -> List[Dict[str, Any]]:
    """Obsolete-drawing check for every found drawing in the store (or `tickers`).

    Prices: /workspace/hist_cache.pkl (same data as the report / near-zone filter).
    refresh=True first appends missing daily bars (stock_screen.refresh_hist_map, only for
    drawn tickers whose cache is behind the last US session, e.g. tickers that dropped out
    of the FinViz list). Writes STALE_JSON / STALE_CSV (all checked tickers, flag '' = ok)
    unless write=False. Returns the rows.
    """
    import report_filters as rf
    import stock_screen as ss

    store = {k: v for k, v in load_store().items() if v.get("found")}
    if tickers:
        want = {csv_ticker(t) for t in tickers}
        store = {k: v for k, v in store.items() if k in want}
    hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    if refresh and store:
        target = ss.last_us_session_date().date()
        behind = [t for t in store if (hist_map.get(t) is None or getattr(hist_map.get(t), "empty", True)
                  or ss._normalize_ohlcv_index(hist_map[t]).index.max().date() < target)]
        if behind:
            print(f"[stale] refreshing cached prices for {len(behind)} drawn tickers: {' '.join(behind)}")
            hist_map = ss.refresh_hist_map(hist_map, behind)
            pd.to_pickle(hist_map, ss.HIST_CACHE)
    rows = []
    for t, rec in sorted(store.items()):
        r = _rec_as_row(t, rec)
        st = rf.compute_stale(_hist_upto(hist_map, t, as_of), r)
        rows.append({"ticker": t, "symbol": rec.get("symbol") or "", "flag": st["tv_stale"] or "",
                     "detail": st["tv_stale_detail"] or "", "zone_bottom": rec.get("zone_bottom"),
                     "zone_top": rec.get("zone_top"), "sl": rec.get("sl"), "tp": rec.get("tp"),
                     "rr": rec.get("rr"), "latest_close": st["latest_close"], "last_bar": st["last_bar"],
                     "weekly_atr": st["weekly_atr"], "dist_above_top_atr": st["dist_above_top_atr"],
                     "read_date": rec.get("read_date")})
    flagged = [r for r in rows if r["flag"]]
    if write and not tickers:
        STALE_JSON.write_text(json.dumps({
            "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
            "as_of": as_of.isoformat() if as_of else "latest cached close",
            "close_basis": rf.CONFIG.get("stale_close_basis", "low"),
            "rules": {"broken": {"low": "any daily low (intraday wick) since the read date < SL, or latest close < SL",
                                 "daily": "any daily close since the read date < SL, or latest close < SL",
                                 "weekly": "weekly close (since read week, incl. current week) < SL, or latest close < SL"
                                 }.get(str(rf.CONFIG.get("stale_close_basis", "low")), ""),
                      "target hit": "latest close >= TP",
                      "far": f"latest close > zone top + {rf.CONFIG['stale_far_atr']:g} x weekly ATR(14)"},
            "checked": len(rows), "flagged": len(flagged),
            "flagged_tickers": [r for r in flagged], "all": rows}, indent=2, default=str) + "\n")
        pd.DataFrame(rows, columns=STALE_FIELDS).to_csv(STALE_CSV, index=False)
        try:  # published copy for the dashboard / charts banner (small JSON, overwritten)
            (REPO / "tv_stale.json").write_text(STALE_JSON.read_text())
        except Exception:
            pass
    if not quiet:
        by = {}
        for r in flagged:
            for f in r["flag"].split(", "):
                by[f] = by.get(f, 0) + 1
        print(f"tv stale: {len(rows)} drawings checked, {len(flagged)} may be obsolete "
              f"({', '.join(f'{k} {v}' for k, v in sorted(by.items())) or 'none'})"
              + (": " + ", ".join(f"{r['ticker']} [{r['flag']}]" for r in flagged) if flagged else ""))
    return rows


BOT_CSV = Path("/workspace/drawing-learn/bot_drawings.csv")
SHOTS_DIR = Path("/workspace/tv_shots")


def _write_json_key(p: Path, key: str, d: Dict[str, Any], **meta: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {**meta, "updated_at": datetime.now(TZ).isoformat(timespec="seconds"), key: dict(sorted(d.items()))}
    p.write_text(json.dumps(body, indent=2, default=str) + "\n")
    import report_filters as rf

    rf._REG_CACHE.pop(str(p), None)  # mtime may not change within the same tick


_BOT_META = {"note": "TradingView drawings made by the bot (Rectangle + Long Position) for needs-drawing tickers. "
                     "source=bot -> 'review needed': NOT counted toward f_rr / PASS / grok_sync_target until "
                     "listed in approved_bot_drawings.json; a read whose levels differ = user-owned."}
_APPROVED_META = {"note": "Bot drawings the user approved (tv_drawings.py bot approve T). Entries with levels "
                          "approve exactly those levels; an approved drawing counts like the user's own."}


def bot_register_levels(t: str, levels: Dict[str, Any], note: str = "", symbol: Optional[str] = None) -> None:
    import report_filters as rf

    reg = dict(rf.load_bot_registry())
    now = datetime.now(TZ).isoformat(timespec="seconds")
    e = dict(reg.get(t) or {})
    e.update({k: levels.get(k) for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr")})
    e.update({"has_level": True, "data_issue": False, "registered_at": e.get("registered_at") or now,
              "drawn_at": now, "note": note})
    if symbol or levels.get("symbol"):
        e["symbol"] = symbol or levels.get("symbol")
    reg[t] = e
    _write_json_key(rf.BOT_REGISTRY, "tickers", reg, **_BOT_META)


def bot_register_csv(path: Path = BOT_CSV, drawn_at: Optional[str] = None) -> Dict[str, Any]:
    """Register every row of the bot's drawing plan (bot_drawings.csv) as source=bot."""
    import report_filters as rf

    reg = dict(rf.load_bot_registry())
    now = drawn_at or datetime.now(TZ).isoformat(timespec="seconds")
    df = pd.read_csv(path)
    for _, b in df.iterrows():
        t = csv_ticker(str(b["ticker"]))
        has = str(b.get("has_level")).strip().lower() == "true"
        e = dict(reg.get(t) or {})
        lv = {k: (None if pd.isna(b.get(k)) else round(float(b.get(k)), 4))
              for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr")}
        same = has and rf.levels_match(e, lv)
        e.update(lv)
        e.update({"symbol": b.get("tv_symbol") or t, "has_level": has,
                  "data_issue": str(b.get("data_issue")).strip().lower() == "true",
                  "kind": None if pd.isna(b.get("kind")) else b.get("kind"),
                  "reason": None if pd.isna(b.get("reason")) else b.get("reason"),
                  "data_date": b.get("data_date"), "tag": b.get("tag"), "source_csv": str(path),
                  "registered_at": e.get("registered_at") or now,
                  "drawn_at": e.get("drawn_at") if same and e.get("drawn_at") else now})
        reg[t] = e
    _write_json_key(rf.BOT_REGISTRY, "tickers", reg, **_BOT_META)
    return reg


def bot_approve(tickers: List[str], approve: bool = True, note: str = "") -> Dict[str, Any]:
    import report_filters as rf

    appr = dict(rf.load_bot_approved())
    reg, store = rf.load_bot_registry(), load_store()
    now = datetime.now(TZ).isoformat(timespec="seconds")
    for raw in tickers:
        t = csv_ticker(raw)
        if not approve:
            appr.pop(t, None)
            continue
        rec = store.get(t) or {}
        src = rec if rec.get("found") else reg.get(t) or {}
        appr[t] = {**{k: src.get(k) for k in ("zone_top", "zone_bottom", "entry", "sl", "tp", "rr")},
                   "approved_at": now, "note": note}
    _write_json_key(rf.BOT_APPROVED, "approved", appr, **_APPROVED_META)
    return appr


def bot_unregister(tickers: List[str]) -> Dict[str, Any]:
    """Remove tickers from the bot registry (e.g. the user drew them himself)."""
    import report_filters as rf

    reg = dict(rf.load_bot_registry())
    for t in tickers:
        reg.pop(csv_ticker(t), None)
    _write_json_key(rf.BOT_REGISTRY, "tickers", reg, **_BOT_META)
    return reg


def bot_status_rows() -> List[Dict[str, Any]]:
    import report_filters as rf

    store = load_store()
    out = []
    for t, b in sorted(rf.load_bot_registry().items()):
        d = rf.drawing_source(t, store.get(t))
        out.append({"ticker": t, "symbol": b.get("symbol"), **d})
    return out


def bot_attach_shots() -> List[str]:
    """Attach /workspace/tv_shots/<T>.png / <T>_bot*.png images written after the bot drew the
    ticker (screenshot only; values untouched; needs a store record)."""
    import report_filters as rf

    store, done = load_store(), []
    for t, b in rf.load_bot_registry().items():
        if not b.get("has_level") or t not in store:
            continue
        since = datetime.fromisoformat(str(b.get("drawn_at") or b.get("registered_at"))).timestamp() - 6 * 3600
        prev = store[t].get("screenshot_at")
        cands = sorted([p for p in SHOTS_DIR.glob(f"{t}*.png")
                        if re.fullmatch(rf"{re.escape(t)}(_bot\w*)?\.png", p.name) and p.stat().st_mtime >= since],
                       key=lambda p: p.stat().st_mtime)
        if not cands:
            continue
        p = cands[-1]
        ts = datetime.fromtimestamp(p.stat().st_mtime, TZ)
        if prev and datetime.fromisoformat(prev) >= ts:
            continue
        store[t].update({"screenshot": save_screenshot(t, p), "screenshot_at": ts.isoformat(timespec="seconds"),
                         "screenshot_date": ts.date().isoformat()})
        done.append(f"{t} <- {p.name}")
    if done:
        save_store(store)
    return done


def merge_files(paths: List[Path], grok_target: bool = True) -> None:
    """Merge the store into each CSV, recompute status, then regenerate grok_sync_target
    from the first (latest) report's status=PASS rows."""
    import stock_screen as ss

    first = None
    rd = date.fromisoformat(_report_date(paths))
    hist_map = pd.read_pickle(ss.HIST_CACHE) if ss.HIST_CACHE.exists() else {}
    for p in paths:
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        base = df[[c for c in df.columns if c not in TV_COLS]]
        out = merge_df(base, report_date=rd, hist_map=hist_map)
        out.to_csv(p, index=False)
        first = out if first is None else first
        n_yes = int((out["tv_found"] == "yes").sum())
        n_no = int((out["tv_found"] == "no").sum())
        n_pass = int((out["status"] == "PASS").sum())
        n_near = int((out["f_near_zone"] == "True").sum())
        n_near_pass = int(((out["f_near_zone"] == "True") & (out["status"] == "PASS")).sum())
        n_nd = int((out["needs_drawing"] == "True").sum())
        n_bot = int((out["f_bot_review"] == "True").sum())
        n_tech = int((out["f_technical"] == "True").sum())
        print(f"merged {p} (as of {rd}): tv_found yes={n_yes} no={n_no}; status PASS={n_pass}; "
              f"f_near_zone={n_near} (PASS {n_near_pass}); needs_drawing={n_nd}; "
              f"bot review needed={n_bot}; technical={n_tech}")
    if grok_target and first is not None:
        from export_daily_report import write_grok_target, write_needs_drawing_target, write_review_target

        gp = write_grok_target(first, _report_date(paths), GROK_TARGET_DIR)
        print(f"grok target {gp}: {json.loads(gp.read_text())['symbols']}")
        np_ = write_needs_drawing_target(first, _report_date(paths), GROK_TARGET_DIR)
        print(f"needs-drawing target {np_}: {json.loads(np_.read_text())['symbols']}")
        rp = write_review_target(first, _report_date(paths), GROK_TARGET_DIR)
        print(f"review target {rp}: {json.loads(rp.read_text())['symbols']}")
    try:  # obsolete-drawing report for ALL found drawings (latest cached closes, no network)
        stale_check(refresh=False)
    except Exception as e:  # never block the merge
        print(f"[stale] skipped: {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("targets", help="write the day's read-target list")
    a.add_argument("--report", type=Path, default=LATEST)
    a.add_argument("--today", default=None)
    a.add_argument("--out-txt", type=Path, default=TARGETS_TXT)
    a.add_argument("--out-json", type=Path, default=TARGETS_JSON)
    u = sub.add_parser("upsert", help="record one ticker's TradingView drawing values")
    u.add_argument("ticker", help="TICKER or EXCHANGE:TICKER")
    u.add_argument("--not-found", action="store_true", help="no drawing found on the chart")
    for k in ("zone-top", "zone-bottom", "entry", "sl", "tp", "rr"):
        u.add_argument(f"--{k}", type=float, default=None)
    u.add_argument("--read-at", default=None, help="ISO datetime of the read (default now, Asia/Jerusalem)")
    u.add_argument("--screenshot", type=Path, default=None,
                   help="chart screenshot (PNG/JPG/WebP on the box); resized <=1280px, WebP <300KB, "
                        "stored as charts/latest/<TICKER>.webp in the repo (overwritten each read)")
    u.add_argument("--source", choices=["user", "bot"], default=None,
                   help="who drew it: bot = review needed (registered in bot_drawings.json), user = user-owned")
    u.add_argument("--label", default=None, help="rectangle text read on the chart ('BOT - review needed' = bot)")
    u.add_argument("--partial", action="store_true",
                   help="drawing found but some values missing (no rectangle / no Long Position / values pending)")
    u.add_argument("--lines-only", action="store_true",
                   help="with --not-found: the chart has only the user's Fib / horizontal lines (not needs drawing)")
    u.add_argument("--drawing-status", default=None, help="short status, e.g. 'user drawing (no rectangle)'")
    u.add_argument("--drawing-note", default=None, help="free-text note shown as tooltip")
    bp = sub.add_parser("bot", help="bot drawings: register / approve / unapprove / list / shots")
    bp.add_argument("action", choices=["register", "unregister", "approve", "unapprove", "list", "shots"])
    bp.add_argument("tickers", nargs="*")
    bp.add_argument("--csv", type=Path, default=BOT_CSV)
    bp.add_argument("--drawn-at", default=None, help="ISO time the bot drew them (default now)")
    bp.add_argument("--note", default="")
    sc = sub.add_parser("screenshot", help="attach/replace only the chart screenshot (values unchanged)")
    sc.add_argument("ticker")
    sc.add_argument("path", type=Path)
    m = sub.add_parser("merge", help="merge store into report CSV(s)")
    m.add_argument("--report", type=Path, action="append", default=None)
    m.add_argument("--today", default=None, help="ignored (kept for compatibility)")
    m.add_argument("--no-grok-target", action="store_true", help="don't regenerate grok_sync_target")
    stp = sub.add_parser("stale", help="flag drawings that may be obsolete (broken / target hit / far)")
    stp.add_argument("--no-refresh", action="store_true", help="don't append missing daily bars first")
    stp.add_argument("--as-of", default=None, help="YYYY-MM-DD cut-off (default: latest cached close)")
    stp.add_argument("--ticker", action="append", default=None, help="check only these (no files written)")
    stp.add_argument("--close-basis", choices=["low", "daily", "weekly"], default=None,
                     help="broken = any daily low < SL since the read date (low, default), "
                          "any daily close < SL (daily) or weekly closes only (weekly)")
    s = sub.add_parser("show")
    s.add_argument("ticker", nargs="?")
    args = ap.parse_args()

    if args.cmd == "targets":
        today = date.fromisoformat(args.today) if args.today else _today()
        df = pd.read_csv(args.report)
        tr = target_rows(df, today)
        syms = tr["tv_symbol"].tolist()
        args.out_txt.write_text("\n".join(syms) + ("\n" if syms else ""))
        args.out_json.write_text(json.dumps({
            "date": today.isoformat(),
            "report": str(args.report),
            "filters": TARGET_FILTERS,
            "note": "f_no_earnings_14d evaluated live vs date (cached earnings date)",
            "count": len(syms),
            "targets": [{"ticker": r.ticker, "symbol": r.tv_symbol, "status": r.status,
                         "smooth_streak_weeks": None if pd.isna(r.smooth_streak_weeks) else int(r.smooth_streak_weeks)}
                        for r in tr.itertuples()],
        }, indent=2) + "\n")
        print(f"{len(syms)} targets -> {args.out_txt}, {args.out_json}")
    elif args.cmd == "upsert":
        if args.not_found:
            rec = upsert(args.ticker, False, read_at=args.read_at, screenshot=args.screenshot,
                         source=args.source, label=args.label, lines_only=args.lines_only,
                         drawing_status=args.drawing_status, drawing_note=args.drawing_note)
        else:
            vals = {"zone_top": args.zone_top, "zone_bottom": args.zone_bottom, "entry": args.entry,
                    "sl": args.sl, "tp": args.tp, "rr": args.rr}
            missing = [k for k, v in vals.items() if v is None]
            if missing and not args.partial:
                ap.error(f"missing values: {', '.join(missing)} (or pass --not-found)")
            rec = upsert(args.ticker, True, read_at=args.read_at, screenshot=args.screenshot,
                         source=args.source, label=args.label, drawing_status=args.drawing_status,
                         drawing_note=args.drawing_note, **vals)
        print(json.dumps({csv_ticker(args.ticker): rec}, indent=2))
        if rec.get("found"):
            try:
                r = stale_check([args.ticker], refresh=False, write=False, quiet=True)
                if r:
                    print(f"stale check {r[0]['ticker']}: {r[0]['flag'] or 'ok'}"
                          + (f" ({r[0]['detail']})" if r[0]["detail"] else ""))
            except Exception as e:
                print(f"[stale] skipped: {e}")
    elif args.cmd == "screenshot":
        t = csv_ticker(args.ticker)
        store = load_store()
        if t not in store:
            ap.error(f"{t}: not in the store; upsert the read (values or --not-found) first")
        rel = save_screenshot(t, args.path)
        now = datetime.now(TZ)
        store[t].update({"screenshot": rel, "screenshot_at": now.isoformat(timespec="seconds"),
                         "screenshot_date": now.date().isoformat()})
        save_store(store)
        print(json.dumps({t: store[t]}, indent=2))
    elif args.cmd == "bot":
        if args.action == "register":
            reg = bot_register_csv(args.csv, args.drawn_at)
            n_lv = sum(1 for v in reg.values() if v.get("has_level"))
            print(f"bot registry: {len(reg)} tickers ({n_lv} with levels, {len(reg) - n_lv} need manual drawing)")
        elif args.action == "unregister":
            reg = bot_unregister(args.tickers)
            print(f"bot registry: {len(reg)} tickers left")
        elif args.action in ("approve", "unapprove"):
            if not args.tickers:
                ap.error("give tickers")
            appr = bot_approve(args.tickers, args.action == "approve", args.note)
            print(f"approved bot drawings: {len(appr)} ({', '.join(sorted(appr)) or 'none'})")
        elif args.action == "shots":
            done = bot_attach_shots()
            print(f"bot screenshots attached: {len(done)}" + (": " + ", ".join(done) if done else ""))
        else:
            rows = bot_status_rows()
            by: Dict[str, int] = {}
            for r in rows:
                by[r["tv_bot_status"]] = by.get(r["tv_bot_status"], 0) + 1
                print(f"  {r['ticker']:<6} {r['tv_source'] or '-':<13} {r['tv_bot_status']:<34} {r['tv_bot_note']}")
            print(f"bot drawings: {len(rows)} " + str(by))
    elif args.cmd == "merge":
        merge_files(args.report or _default_reports(), grok_target=not args.no_grok_target)
    elif args.cmd == "stale":
        if args.close_basis:
            import report_filters as rf

            rf.CONFIG["stale_close_basis"] = args.close_basis
        rows = stale_check(args.ticker, as_of=date.fromisoformat(args.as_of) if args.as_of else None,
                           refresh=not args.no_refresh)
        for r in rows:
            if r["flag"]:
                print(f"  {r['symbol'] or r['ticker']:<14} {r['flag']:<18} zone {r['zone_bottom']}-{r['zone_top']} "
                      f"SL {r['sl']} TP {r['tp']} close {r['latest_close']} ({r['last_bar']}) "
                      f"{r['dist_above_top_atr']} ATR vs top | {r['detail']}")
        if not args.ticker:
            print(f"-> {STALE_JSON}, {STALE_CSV}")
    elif args.cmd == "show":
        st = load_store()
        print(json.dumps(st.get(args.ticker.upper()) if args.ticker else st, indent=2))


if __name__ == "__main__":
    main()
