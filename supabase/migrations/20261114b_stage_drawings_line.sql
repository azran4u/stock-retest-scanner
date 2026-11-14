-- Stages page (Eyal 2026-11-14): his support / resistance lines (kind 'line', price in entry; meta.ref = the computed
-- level he moved / hid, meta.role = 'res' | 'sup' for a level he added, meta.hidden = a computed level he deleted).
alter table public.stage_drawings drop constraint if exists stage_drawings_kind_check;
alter table public.stage_drawings add constraint stage_drawings_kind_check check (kind in ('zone', 'long', 'line'));
