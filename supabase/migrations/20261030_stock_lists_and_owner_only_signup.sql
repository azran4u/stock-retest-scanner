create table if not exists public.stock_lists (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  kind text not null check (kind in ('static','dynamic')),
  tickers text[] not null default '{}',
  criteria jsonb,
  pos int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.stock_lists enable row level security;
create policy owner_all on public.stock_lists for all to authenticated
  using ((auth.jwt() ->> 'email') = 'azran4u@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'azran4u@gmail.com');
alter publication supabase_realtime add table public.stock_lists;

create or replace function public.srs_owner_only_signup() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if lower(coalesce(new.email, '')) <> 'azran4u@gmail.com' then
    raise exception 'sign-ups are restricted to the owner account';
  end if;
  return new;
end $$;
revoke execute on function public.srs_owner_only_signup() from public, anon, authenticated;
create trigger srs_owner_only_signup before insert or update of email on auth.users
  for each row execute function public.srs_owner_only_signup();
