-- Telegram secrets are set from the box through srs-price-alerts (?setup=telegram, upload-token auth), so the token
-- never passes through SQL text / logs. Only the service role may call this, and only for the two Telegram names.
create or replace function public.srs_alert_set_secret(n text, v text) returns void
language plpgsql security definer set search_path = '' as $$
declare sid uuid;
begin
  if n not in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID') then raise exception 'name not allowed'; end if;
  select id into sid from vault.secrets where name = n;
  if sid is null then perform vault.create_secret(v, n); else perform vault.update_secret(sid, v); end if;
end $$;
revoke all on function public.srs_alert_set_secret(text, text) from public, anon, authenticated;
grant execute on function public.srs_alert_set_secret(text, text) to service_role;
