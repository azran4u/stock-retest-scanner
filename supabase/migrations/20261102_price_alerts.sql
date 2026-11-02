-- Real-time price alerts to Telegram (Eyal 2026-11-02): edge function srs-price-alerts, run by pg_cron every 10 minutes.
create extension if not exists pg_cron;

create table if not exists public.price_alerts (
  id bigint generated always as identity primary key,
  ticker text not null,
  kind text not null check (kind in ('near', 'touch')),
  trade_day date not null,                          -- America/New_York session date
  live boolean not null,                            -- false = dry-run (logged only, not sent)
  price numeric, entry numeric, stop numeric, target numeric, rr numeric, dist_atr numeric,
  source text,                                      -- own | expert | bot
  message text not null,
  telegram jsonb,
  created_at timestamptz not null default now(),
  unique (ticker, kind, trade_day, live)            -- at most one alert per type / ticker / trading day
);
alter table public.price_alerts enable row level security;
create policy owner_select on public.price_alerts for select to authenticated using ((auth.jwt() ->> 'email') = 'azran4u@gmail.com');

create table if not exists public.alert_runs (
  id int primary key default 1 check (id = 1),      -- single status row the app shows ("התראות פעילות")
  last_run timestamptz, mode text, market text, checked int, sent int, note text, error text
);
alter table public.alert_runs enable row level security;
create policy owner_select on public.alert_runs for select to authenticated using ((auth.jwt() ->> 'email') = 'azran4u@gmail.com');

-- secrets live in Supabase Vault; only the service role (edge function) can read them, and only these names
create or replace function public.srs_alert_secret(n text) returns text
language sql security definer set search_path = '' as $$
  select decrypted_secret from vault.decrypted_secrets
  where name = n and n in ('srs_alert_cron_token', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID') limit 1
$$;
revoke all on function public.srs_alert_secret(text) from public, anon, authenticated;
grant execute on function public.srs_alert_secret(text) to service_role;

-- random token the cron job sends in x-srs-cron (never leaves the database)
select vault.create_secret(encode(extensions.gen_random_bytes(24), 'hex'), 'srs_alert_cron_token', 'pg_cron -> srs-price-alerts')
where not exists (select 1 from vault.secrets where name = 'srs_alert_cron_token');

-- every 10 minutes, Mon-Fri, 13:00-21:59 UTC = covers 09:30-16:00 ET in both EDT and EST; the function checks the
-- New York clock and holidays itself and returns 'skipped' outside the session.
select cron.unschedule('srs-price-alerts') where exists (select 1 from cron.job where jobname = 'srs-price-alerts');
select cron.schedule('srs-price-alerts', '*/10 13-21 * * 1-5', $$
  select net.http_post(
    url := 'https://wkkdblnykgolqijzagva.supabase.co/functions/v1/srs-price-alerts',
    headers := jsonb_build_object('Content-Type', 'application/json',
      'x-srs-cron', (select decrypted_secret from vault.decrypted_secrets where name = 'srs_alert_cron_token')),
    body := '{}'::jsonb, timeout_milliseconds := 60000)
$$);
