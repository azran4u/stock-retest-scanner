# Supabase (project wkkdblnykgolqijzagva) — applied with the Supabase MCP, kept here for the record

- `migrations/20261030_stock_lists_and_owner_only_signup.sql` — `stock_lists` (owner-only RLS, realtime) + trigger that
  rejects any new auth user whose email is not the owner's (Google or email sign-in).
- `migrations/20261030_private_app_data_bucket.sql` — private Storage bucket `app-data` (read: owner's login only) +
  hashed upload token for the nightly upload.
- `functions/srs-data-upload` — edge function the nightly export posts the app data to (`srs_app/publish_data.py`).
- `migrations/20261102_price_alerts.sql` + `20261102b_price_alerts_set_secret.sql` — real-time Telegram price alerts:
  tables `price_alerts` (one alert per type / ticker / NY trading day) and `alert_runs` (status row the app shows),
  Vault secrets (`srs_alert_cron_token`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), pg_cron job `srs-price-alerts`
  (`*/10 13-21 * * 1-5` UTC; the function itself checks 09:30–16:00 America/New_York, NYSE holidays / early closes).
- `functions/srs-price-alerts` — starred tickers (`watchlist`) vs entry = Eyal's own Long (drawings user/tv) → expert
  trade (`expert_zones.json`) → bot Long; Yahoo chart quotes (5m, session high/low); alerts 'near' (≤ 0.25 weekly ATR)
  and 'touch' (session range reached / gapped through the entry). Tests: `deno test supabase/functions/srs-price-alerts`.
  Manual run (from SQL, the cron token stays in Vault): `net.http_post(url || '?dry=1&force=1', headers x-srs-cron …)`.
  Set / rotate Telegram secrets from the box (token never printed): POST `?setup=telegram` with header `x-srs-token`
  (nightly upload token) and body `{"token": …, "chat_id": …}`.
