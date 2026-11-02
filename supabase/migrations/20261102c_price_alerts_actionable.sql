-- Actionable-only alerts (Eyal 2026-11-02): kinds limit / triggered / cancel (near / touch kept for the history rows).
alter table public.price_alerts drop constraint if exists price_alerts_kind_check;
alter table public.price_alerts add constraint price_alerts_kind_check check (kind in ('near', 'touch', 'limit', 'triggered', 'cancel'));
create index if not exists price_alerts_ticker_day on public.price_alerts (ticker, trade_day desc);
