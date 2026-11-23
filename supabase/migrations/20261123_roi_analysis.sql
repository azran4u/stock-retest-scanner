-- roi_analysis: Roi's method checklist + recommendation for PASS tickers (ניתוח רועי).
-- Private. Do NOT put this data in a static file under app/ or dist/: those folders are
-- publicly reachable without login (the app is a static SPA; auth is client-side).
-- RLS matches lives / ticker_research: only the signed-in owner can SELECT.
-- Writes are not granted to authenticated; refresh by re-running tools/import_roi.py
-- (service role / dashboard bypasses RLS). Upsert key: ticker (replace, do not merge).

create table if not exists public.roi_analysis (
  ticker               text primary key,
  recommendation       text not null,
  rec_key              text not null check (rec_key in ('enter', 'wait', 'skip')),
  entry                numeric,
  stop                 numeric,
  target               numeric,
  rr                   numeric,
  rationale_he         text,
  checklist            jsonb not null default '[]'::jsonb,
  roi_mentions         jsonb not null default '[]'::jsonb,
  as_of                date,
  price                numeric,
  price_date           date,
  zone_top             numeric,
  zone_bottom          numeric,
  stop_pct             numeric,
  adv                  numeric,
  earnings_date        date,
  days_to_earnings     int,
  scanner_report_date  date,
  trigger_he           text,
  dist_atr             numeric,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create index if not exists roi_analysis_rec_key_idx on public.roi_analysis (rec_key);

alter table public.roi_analysis enable row level security;

drop policy if exists owner_select on public.roi_analysis;
create policy owner_select on public.roi_analysis
  for select to authenticated
  using ((auth.jwt() ->> 'email') = 'azran4u@gmail.com');

revoke all on table public.roi_analysis from anon, public, authenticated;
grant select on table public.roi_analysis to authenticated;
