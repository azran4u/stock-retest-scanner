#!/usr/bin/env python3
"""Build upsert SQL (and optional JSON) for public.lives from a lives_all.csv export.

Keyed on youtube_id (fallback: the id parsed from the YouTube link). Duplicate
youtube_ids are folded into one row, keeping the earliest post_date.

This script only writes files. It does not connect to Supabase.

Usage:
  python tools/import_lives.py /path/to/lives_all.csv \\
      --sql /workspace/lives/lives_import.sql \\
      --json /workspace/lives/lives.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

YID_RE = re.compile(r'(?:v=|/embed/|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})')


def clean(s: str | None) -> str:
    return (s or '').strip()


def parse_date(s: str | None) -> str | None:
    s = clean(s)
    if not s:
        return None
    return datetime.strptime(s, '%Y-%m-%d').date().isoformat()


def parse_stocks(s: str | None) -> list[str]:
    return [t for t in re.split(r'\s+', clean(s)) if t]


def youtube_id_of(row: dict) -> str:
    yid = clean(row.get('youtube_id'))
    if yid:
        return yid
    link = clean(row.get('link'))
    m = YID_RE.search(link)
    return m.group(1) if m else ''


def normalize_row(row: dict, src_row: int) -> dict | None:
    yid = youtube_id_of(row)
    link = clean(row.get('link'))
    if not yid and not link:
        return None
    live_date = parse_date(row.get('live_date'))
    post_date = parse_date(row.get('post_date')) or live_date
    rec = {
        'youtube_id': yid or link,
        'link': link or (f'https://youtu.be/{yid}' if yid else ''),
        'archive': clean(row.get('archive')) or 'community',
        'live_date': live_date,
        'post_date': post_date,
        'post_time': clean(row.get('post_time')) or None,
        'mentor': clean(row.get('mentor')) or 'לא צוין',
        'title': clean(row.get('title')) or 'הקלטת לייב',
        'summary_link': clean(row.get('summary_link')) or None,
        'stocks': parse_stocks(row.get('stocks')),
        'topics': clean(row.get('topics')) or None,
        'notes': clean(row.get('notes')) or None,
        '_src_row': src_row,
    }
    rec['display_date'] = rec['live_date'] or rec['post_date']
    return rec


def load_csv(path: Path) -> tuple[list[dict], list[tuple]]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        raw = list(csv.DictReader(f))
    by_id: dict[str, dict] = {}
    dupes = []
    for i, r in enumerate(raw, start=2):
        rec = normalize_row(r, i)
        if not rec:
            continue
        yid = rec['youtube_id']
        if yid in by_id:
            prev = by_id[yid]
            dupes.append((yid, prev, rec))
            key = lambda x: (x['post_date'] or '9999', x['post_time'] or '99:99')
            if key(rec) < key(prev):
                by_id[yid] = rec
            continue
        by_id[yid] = rec
    lives = list(by_id.values())
    lives.sort(key=lambda x: (x['display_date'] or '', x['post_time'] or '', x['youtube_id']), reverse=True)
    for rec in lives:
        rec.pop('_src_row', None)
    return lives, dupes


def sql_str(v: str | None) -> str:
    if v is None:
        return 'NULL'
    return "'" + str(v).replace("'", "''") + "'"


def sql_time(v: str | None) -> str:
    return 'NULL' if not v else sql_str(v) + '::time'


def sql_text_arr(xs: list[str]) -> str:
    if not xs:
        return "'{}'::text[]"
    inner = ','.join('"' + t.replace('\\', '\\\\').replace('"', '\\"') + '"' for t in xs)
    return "'" + inner + "'::text[]"


def render_import_sql(lives: list[dict], n_csv: int, n_dupes: int) -> str:
    lines = [
        '-- Upsert of Cycles Trading lives from lives_all.csv.',
        '-- Key: youtube_id. Re-run after a new CSV export to refresh.',
        f'-- Source rows: {n_csv}; unique youtube_id: {len(lives)}; folded duplicates: {n_dupes}.',
        '-- Do not apply until approved. Service role / SQL editor bypasses RLS.',
        '',
        'insert into public.lives (',
        '  youtube_id, link, archive, live_date, post_date, post_time,',
        '  mentor, title, summary_link, stocks, topics, notes, updated_at',
        ')',
        'values',
    ]
    vals = []
    for rec in lives:
        vals.append('  (' + ', '.join([
            sql_str(rec['youtube_id']),
            sql_str(rec['link']),
            sql_str(rec['archive']),
            sql_str(rec['live_date']),
            sql_str(rec['post_date']),
            sql_time(rec['post_time']),
            sql_str(rec['mentor']),
            sql_str(rec['title']),
            sql_str(rec['summary_link']),
            sql_text_arr(rec['stocks']),
            sql_str(rec['topics']),
            sql_str(rec['notes']),
            'now()',
        ]) + ')')
    lines.append(',\n'.join(vals))
    lines += [
        'on conflict (youtube_id) do update set',
        '  link = excluded.link,',
        '  archive = excluded.archive,',
        '  live_date = excluded.live_date,',
        '  post_date = excluded.post_date,',
        '  post_time = excluded.post_time,',
        '  mentor = excluded.mentor,',
        '  title = excluded.title,',
        '  summary_link = excluded.summary_link,',
        '  stocks = excluded.stocks,',
        '  topics = excluded.topics,',
        '  notes = excluded.notes,',
        '  updated_at = now();',
        '',
    ]
    return '\n'.join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv', type=Path)
    p.add_argument('--sql', type=Path, help='Write upsert SQL here')
    p.add_argument('--json', type=Path, help='Write normalized JSON here (keep outside app/ and dist/)')
    args = p.parse_args()
    with args.csv.open(encoding='utf-8-sig', newline='') as f:
        n_csv = sum(1 for _ in csv.DictReader(f))
    lives, dupes = load_csv(args.csv)
    if args.sql:
        args.sql.parent.mkdir(parents=True, exist_ok=True)
        args.sql.write_text(render_import_sql(lives, n_csv, len(dupes)), encoding='utf-8')
        print(f'wrote {args.sql} ({len(lives)} rows)')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(lives, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'wrote {args.json} ({len(lives)} rows)')
    if not args.sql and not args.json:
        print(f'{len(lives)} unique lives from {n_csv} CSV rows; {len(dupes)} folded duplicates')
        for yid, a, b in dupes:
            print(f'  duplicate {yid}: kept {a["post_date"]} {a["post_time"]}, dropped {b["post_date"]} {b["post_time"]}')


if __name__ == '__main__':
    main()
