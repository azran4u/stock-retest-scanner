# Supabase (project wkkdblnykgolqijzagva) — applied with the Supabase MCP, kept here for the record

- `migrations/20261030_stock_lists_and_owner_only_signup.sql` — `stock_lists` (owner-only RLS, realtime) + trigger that
  rejects any new auth user whose email is not the owner's (Google or email sign-in).
- `migrations/20261030_private_app_data_bucket.sql` — private Storage bucket `app-data` (read: owner's login only) +
  hashed upload token for the nightly upload.
- `functions/srs-data-upload` — edge function the nightly export posts the app data to (`srs_app/publish_data.py`).
