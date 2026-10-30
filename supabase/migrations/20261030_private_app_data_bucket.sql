insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('app-data', 'app-data', false, 52428800, array['application/json'])
on conflict (id) do update set public = false;
create policy "srs app-data owner read" on storage.objects for select to authenticated
  using (bucket_id = 'app-data' and (auth.jwt() ->> 'email') = 'azran4u@gmail.com');

create schema if not exists srs_private;
revoke all on schema srs_private from public, anon, authenticated;
create table if not exists srs_private.upload_tokens (name text primary key, sha256 text not null, created_at timestamptz default now());
revoke all on srs_private.upload_tokens from public, anon, authenticated;
-- the token itself stays on the box (/workspace/.secrets/srs_upload_token); only its SHA-256 is stored:
-- insert into srs_private.upload_tokens (name, sha256) values ('nightly', '<sha256 hex>') on conflict (name) do update set sha256 = excluded.sha256;

create or replace function public.srs_check_upload_token(t text) returns boolean
language sql security definer set search_path = '' stable as $$
  select exists (select 1 from srs_private.upload_tokens where sha256 = encode(extensions.digest(t, 'sha256'), 'hex'));
$$;
revoke execute on function public.srs_check_upload_token(text) from public, anon, authenticated;
grant execute on function public.srs_check_upload_token(text) to service_role;
