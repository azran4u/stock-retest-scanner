#!/usr/bin/env python3
"""Build upsert SQL for public.roi_analysis from the Discord bot's pass_analysis.json
(or the CSV twin).

Keyed on ticker. On conflict, every column is replaced (checklist and mentions included;
nothing is merged). This script only writes files. It does not connect to Supabase.

Usage:
  python tools/import_roi.py /workspace/discord/roi/pass_analysis.json \\
      --sql /workspace/roi/roi_import.sql
  python tools/import_roi.py /workspace/discord/roi/pass_analysis.csv --sql out.sql
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

REC_PREFIXES = (
    ('enter', 'כניסה עכשיו'),
    ('wait', 'לחכות לאישור'),
    ('skip', 'לדלג'),
)


def rec_key_of(recommendation: str, explicit: str | None = None) -> str | None:
    if explicit in {'enter', 'wait', 'skip'}:
        return explicit
    s = (recommendation or '').strip()
    for key, prefix in REC_PREFIXES:
        if s == key or s.startswith(prefix):
            return key
    return None


def blank(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def num(v) -> float | None:
    if v is None or v == '':
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n == n else None  # not NaN


def parse_jsonish(v):
    if v is None or v == '':
        return []
    if isinstance(v, (list, dict)):
        return v
    s = str(v).strip()
    if not s:
        return []
    return json.loads(s)


def normalize_row(raw: dict) -> dict | None:
    ticker = (raw.get('ticker') or '').strip().upper()
    if not ticker:
        return None
    recommendation = (raw.get('recommendation') or '').strip()
    rec_key = rec_key_of(recommendation, blank(raw.get('rec_key')))
    if not rec_key:
        return None
    checklist = parse_jsonish(raw.get('checklist')) or []
    mentions = parse_jsonish(raw.get('roi_mentions')) or []
    if not isinstance(checklist, list):
        checklist = []
    if not isinstance(mentions, list):
        mentions = []
    return {
        'ticker': ticker,
        'recommendation': recommendation or rec_key,
        'rec_key': rec_key,
        'entry': num(raw.get('entry')),
        'stop': num(raw.get('stop')),
        'target': num(raw.get('target')),
        'rr': num(raw.get('rr')),
        'rationale_he': blank(raw.get('rationale_he')),
        'checklist': checklist,
        'roi_mentions': mentions,
        'as_of': blank(raw.get('as_of')),
        'price': num(raw.get('price')),
        'price_date': blank(raw.get('price_date')),
        'zone_top': num(raw.get('zone_top')),
        'zone_bottom': num(raw.get('zone_bottom')),
        'stop_pct': num(raw.get('stop_pct')),
        'adv': num(raw.get('adv')),
        'earnings_date': blank(raw.get('earnings_date')),
        'days_to_earnings': None if raw.get('days_to_earnings') in (None, '') else int(raw['days_to_earnings']),
        'scanner_report_date': blank(raw.get('scanner_report_date')),
        'trigger_he': blank(raw.get('trigger_he')),
        'dist_atr': num(raw.get('dist_atr')),
    }


def load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == '.json':
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(raw, dict):
            raw = raw.get('rows') or raw.get('tickers') or raw.get('items') or raw.get('data') or list(raw.values())
        if not isinstance(raw, list):
            raise SystemExit(f'unexpected JSON shape in {path}')
        src = raw
    else:
        with path.open(encoding='utf-8-sig', newline='') as f:
            src = list(csv.DictReader(f))
    out, seen = [], set()
    skipped = 0
    for r in src:
        if not isinstance(r, dict):
            skipped += 1
            continue
        row = normalize_row(r)
        if not row:
            skipped += 1
            continue
        if row['ticker'] in seen:
            # keep the later row (file order) by replacing
            out = [x for x in out if x['ticker'] != row['ticker']]
        seen.add(row['ticker'])
        out.append(row)
    if skipped:
        print(f'skipped {skipped} rows without a ticker/recommendation')
    return out


def sql_str(v: str | None) -> str:
    if v is None:
        return 'NULL'
    return "'" + v.replace("'", "''") + "'"


def sql_num(v: float | int | None) -> str:
    if v is None:
        return 'NULL'
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e12):
        # keep days_to_earnings as int; other numbers may be .0
        pass
    # compact but exact-enough
    if isinstance(v, float):
        s = format(v, '.12g')
        return s
    return str(v)


def sql_json(v) -> str:
    blob = json.dumps(v, ensure_ascii=False, separators=(',', ':'))
    tag = 'j'
    while f'${tag}$' in blob:
        tag += 'x'
    return f"${tag}${blob}${tag}$::jsonb"


COLS = [
    'ticker', 'recommendation', 'rec_key', 'entry', 'stop', 'target', 'rr',
    'rationale_he', 'checklist', 'roi_mentions', 'as_of', 'price', 'price_date',
    'zone_top', 'zone_bottom', 'stop_pct', 'adv', 'earnings_date',
    'days_to_earnings', 'scanner_report_date', 'trigger_he', 'dist_atr',
    'updated_at',
]

JSON_COLS = {'checklist', 'roi_mentions'}
NUM_COLS = {
    'entry', 'stop', 'target', 'rr', 'price', 'zone_top', 'zone_bottom',
    'stop_pct', 'adv', 'days_to_earnings', 'dist_atr',
}


def value_sql(row: dict) -> str:
    parts = []
    for c in COLS:
        if c == 'updated_at':
            parts.append('now()')
        elif c in JSON_COLS:
            parts.append(sql_json(row[c]))
        elif c in NUM_COLS:
            parts.append(sql_num(row[c]))
        else:
            parts.append(sql_str(row[c]))
    return '(' + ', '.join(parts) + ')'


def render_batch(rows: list[dict]) -> str:
    update_cols = [c for c in COLS if c not in ('ticker', 'updated_at')]
    lines = [
        'insert into public.roi_analysis (',
        '  ' + ', '.join(COLS),
        ')',
        'values',
        ',\n'.join('  ' + value_sql(r) for r in rows),
        'on conflict (ticker) do update set',
        ',\n'.join(f'  {c} = excluded.{c}' for c in update_cols) + ',',
        '  updated_at = now();',
        '',
    ]
    return '\n'.join(lines)


def render_import_sql(rows: list[dict], batch_size: int = 25) -> str:
    parts = [
        '-- Upsert of Roi PASS analysis. Key: ticker. Every column is replaced (not merged).',
        f'-- {len(rows)} unique tickers. Re-run after a new pass_analysis.json export.',
        '-- Do not apply until approved. Service role / SQL editor bypasses RLS.',
        '',
    ]
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        parts.append(f'-- batch {i // batch_size + 1} ({len(chunk)} rows)')
        parts.append(render_batch(chunk))
    return '\n'.join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('src', type=Path, help='pass_analysis.json or .csv')
    p.add_argument('--sql', type=Path, help='Write upsert SQL here')
    p.add_argument('--batch-size', type=int, default=25)
    args = p.parse_args()
    rows = load_rows(args.src)
    keys = {}
    for r in rows:
        keys[r['rec_key']] = keys.get(r['rec_key'], 0) + 1
    print(f'{len(rows)} unique tickers; rec_key counts: {keys}')
    if args.sql:
        args.sql.parent.mkdir(parents=True, exist_ok=True)
        args.sql.write_text(render_import_sql(rows, args.batch_size), encoding='utf-8')
        print(f'wrote {args.sql} ({args.sql.stat().st_size} bytes)')
    if not args.sql:
        print('no --sql path; nothing written')


if __name__ == '__main__':
    main()
