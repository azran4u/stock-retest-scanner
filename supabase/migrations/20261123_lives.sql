-- lives: Cycles Trading community live-session archive (לייבים).
-- Private community content. Do NOT put this data in a static file under app/ or dist/:
-- those folders are publicly reachable without login (the app is a static SPA; auth is client-side).
-- RLS matches the app's other tables: only the signed-in owner can SELECT.
-- Writes are not granted to authenticated; refresh by re-running the import SQL / script
-- (service role / dashboard bypasses RLS).
-- Generated 2026-11-23. Apply manually after Eyal approves. Do not apply automatically.

create table if not exists public.lives (
  youtube_id    text primary key,
  link          text not null,
  archive       text not null check (archive in ('students', 'community')),
  live_date     date,
  post_date     date not null,
  post_time     time,
  mentor        text,
  title         text not null,
  summary_link  text,
  stocks        text[] not null default '{}',
  topics        text,
  notes         text,
  display_date  date generated always as (coalesce(live_date, post_date)) stored,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists lives_display_date_idx on public.lives (display_date desc);
create index if not exists lives_mentor_idx on public.lives (mentor);
create index if not exists lives_archive_idx on public.lives (archive);
create index if not exists lives_stocks_idx on public.lives using gin (stocks);

alter table public.lives enable row level security;

drop policy if exists owner_select on public.lives;
create policy owner_select on public.lives
  for select to authenticated
  using ((auth.jwt() ->> 'email') = 'azran4u@gmail.com');

-- authenticated may only read; no insert/update/delete policy on purpose.
-- Revoke from authenticated too: Supabase default privileges otherwise grant ALL.
revoke all on table public.lives from anon, public, authenticated;
grant select on table public.lives to authenticated;
