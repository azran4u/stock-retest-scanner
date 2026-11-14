-- Weinstein stages page (#/stages, Eyal 2026-11-14): his edits of the base ceiling / floor (kind 'zone') and of the
-- Buy-Stop trade bar (kind 'long': entry / stop / target). Separate from public.drawings on purpose: the retest scanner,
-- its zones and the srs-price-alerts Telegram function never read this table. His row (source 'user') overrides the
-- computed levels on the page; R:R is recomputed from it. Owner-only RLS like every other table.
create table if not exists public.stage_drawings (
  id uuid primary key default gen_random_uuid(),
  ticker text not null,
  kind text not null check (kind in ('zone', 'long')),
  zone_top numeric, zone_bottom numeric, entry numeric, stop numeric, target numeric,
  t_start date, t_end date,
  source text not null default 'user' check (source in ('user')),
  status text not null default 'active' check (status in ('active', 'deleted')),
  meta jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists stage_drawings_ticker on public.stage_drawings (ticker);
alter table public.stage_drawings enable row level security;
drop policy if exists owner_all on public.stage_drawings;
create policy owner_all on public.stage_drawings for all to authenticated
  using ((auth.jwt() ->> 'email') = 'azran4u@gmail.com') with check ((auth.jwt() ->> 'email') = 'azran4u@gmail.com');
grant select, insert, update, delete on public.stage_drawings to authenticated;
