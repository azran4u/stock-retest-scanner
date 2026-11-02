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

## Price alerts — actionable only (Eyal 2026-11-02: "אל תשלח הודעה אם אין לי מה לעשות איתה")

Tracked every 10 minutes in the US session: the starred tickers (`watchlist`) + the hot list (`app-data/expert_watch.json`).
Setup per ticker = his own Long / zone (drawings `user` / `tv` = his override, per kind) else the expert trade / zone
(`expert_zones.json`, v7 breakout retest). No clear retest and no Long of his → nothing is tracked for it.

A setup is **valid** when: the expert zone is intact (expert source), R:R ≥ 2, no earnings within 14 days and no report
reacted to this week or in the last completed week, and the stock is in a primary uptrend (`f_technical` from
`index.json`; no report row → allowed with the note "מגמה: אין נתון בדוח").

| Alert | When | What he does |
|---|---|---|
| 📌 `limit` "שווה לשים פקודה" | valid setup, price ≤ 0.25 weekly ATR above the entry (approaching), or inside the zone under the entry | buy limit at the entry (price above it) / buy-stop at the entry (price inside the zone); SL / TP / shares for $55 risk in the message |
| ✅ `triggered` "הכניסה הופעלה" | valid setup, the session traded at / under the entry and price is back above it, still ≤ 0.5 ATR above (not run away) | the limit filled — or enter now if he has no position |
| ❌ `cancel` "בטל את הפקודה" | price ≤ SL, or the expert zone stopped being valid, AND an order may be working (a limit / triggered alert was sent for this entry in the last 30 days) or the stock is starred | cancel the open buy order |

**No message** when: the setup is invalid (R:R < 2, earnings, no uptrend, zone broken without an order), price ran away
(> 0.25 ATR above for a new limit, > 0.5 ATR for triggered), price is under the zone but above SL (moving away — e.g.
SNX 2026-11-02, 0.5 ATR under the entry, used to be a "touched" message), or there is no weekly ATR.

**Dedup / cooldown:** one alert per type / ticker / New York trading day (unique key), and the same kind for the same
levels (entry / SL / TP within 0.5%) is not repeated for 5 days (limit / triggered) or 30 days (cancel) unless the
levels changed. Manual tests: `?dry=1&force=1` (never sends, never consumes a slot). Code: `logic.ts` `decide()`,
tests `deno test supabase/functions/srs-price-alerts` (`/workspace/.deno-bin/deno` on the box).
