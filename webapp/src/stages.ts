import { researchHtml, isoLtr, type Research } from './research';
// Weinstein stage analysis page (#/stages, 'שלבים', Eyal 2026-11-13). Data: stages.json + stages_spark.json from
// srs_app/stages.py (own FinViz screen + weekly history; separate from the retest scanner). Every stock gets a stage
// 1-4 + sub-stage + the module-3 identification checks of its stage (✓ / ✗) so Eyal can verify the classification;
// 2A = new stage-2 breakout. Rules come from his masterclass page; the thresholds are printed on the page.

export interface Check { k: string; ok: boolean | null; he: string; info?: boolean }
export interface Plan {
  kind: 'breakout' | 'trigger' | 'continuation'; entry: number; stop: number; stop_basis: 'low' | 'ma' | 'hl'; swing_low: number | null; anchor_b?: number | null; stop_anchor?: number | null; target: number | null;
  target_src: 'overhead' | 'open_sky' | null; risk_pct: number | null; stop_wide: boolean; rr: number | null; shares: number | null;
  overhead: number | null; overhead_pct: number | null; open_sky: boolean; ath: boolean; cong: number | null; hi2y: number | null;
  level: number; close_vs_level: number | null; entry_vs_ma: number | null; chase: boolean; vol_need?: number | null; ov_levels?: number[];
}
export interface ShortPlan {
  kind: 'breakdown' | 'trigger' | 'continuation'; entry: number; stop: number; stop_basis: 'high' | 'ma' | 'lh'; swing_high: number | null; anchor_b?: number | null; stop_anchor?: number | null; target: number | null;
  target_src: 'support' | 'open_sky' | null; risk_pct: number | null; stop_wide: boolean; rr: number | null; shares: number | null; pos_usd?: number | null;
  support: number | null; support_pct: number | null; open_sky: boolean; atl: boolean; cong: number | null; lo2y: number | null;
  level: number; close_vs_level: number | null; entry_vs_ma: number | null; chase: boolean; sup_levels?: number[];
}
export interface StageRow {
  t: string; n: string; ex: string; sec: string; ind: string; etf: string | null; etf_stage: number | null; etf_rs: number | null; ind_etf?: string | null; sec_etf?: string | null; sec_etf_stage?: number | null; atr_w?: number | null;
  mcap_b: number | null; inst: number | null; short_float?: number | null; dv_m: number | null; earn: string | null; earn_td: number | null;
  stage: 1 | 2 | 3 | 4; sub: string; score: number; conf: 'high' | 'med' | 'low'; checks: Check[]; week: string;
  close: number; ma30: number; slope: number; slope_cls: string; pct_ma: number; rs: number | null; rs_prev: number | null; rs_up: boolean | null;
  hh: boolean | null; hl: boolean | null; prior: string; flat_w: number; crosses13: number; hi52: number; pct_hi52: number; at_hi52: boolean; weeks: number;
  bo: null | { week: string; weeks_ago: number; level: number; base_weeks: number; base_low: number; vol_ratio: number | null; close_pos: number | null; holding: boolean; vol_ok: boolean; pct_above: number | null; in_range?: boolean; res_week?: string };
  bd?: null | { week: string; weeks_ago: number; level: number; base_weeks: number; base_high: number; vol_ratio: number | null; close_pos: number | null; holding: boolean; vol_ok: boolean; pct_below: number | null; in_range?: boolean; sup_week?: string };
  base?: { top: number; low: number; weeks: number; dist_pct: number; since_top_w?: number; top_week?: string | null; mature?: boolean };
  short_base?: { floor: number; top: number; weeks: number; dist_pct: number; since_bot_w?: number; bot_week?: string | null; mature?: boolean };
  range?: { ceil: number | null; floor: number | null; since_w: number; since: string | null };
  plan?: Plan; short_plan?: ShortPlan; pre: Check[]; pre_ok: boolean; entry: Check[]; entry_ok: boolean; bs?: boolean;
  short_entry?: Check[]; short_entry_ok?: boolean; ss?: boolean;
  earn_eff?: string | null; earn_timing?: 'a' | 'b' | null; earn_live_week?: boolean;
  earn_est?: boolean; earn_last?: string | null; earn_last_ago?: number | null; earn_block?: boolean; post_earn?: string | null; post_gap?: boolean;
  post_earn_short?: string | null; post_gap_short?: boolean;
}
export interface IdxInfo { pos: 'above' | 'below' | 'cross'; above_n: number; of_w: number; crosses13: number; struct: 'HH/HL' | 'LH/LL' | 'mixed'; swing_hi: number[]; swing_lo: number[]; swing_hi_w?: string[]; swing_lo_w?: string[]; support: number | null; resistance: number | null; broke_support: boolean; td: string; td_he: string }
export interface EtfStage { idx?: IdxInfo; td?: string; td_he?: string; short_td?: string; short_td_he?: string; hh?: boolean | null; hl?: boolean | null; sec_ok?: boolean | null; sec_case?: string | null; sec_he?: string; short_sec_ok?: boolean | null; short_sec_case?: string | null; short_sec_he?: string; range?: StageRow['range']; bo?: StageRow['bo']; base?: StageRow['base']; weeks?: number; slope_cls?: string; atr_w?: number | null; name: string; stage: number; sub: string; score: number; conf: string; close: number; ma30: number; slope: number; pct_ma: number; rs: number | null; rs_up: boolean | null; week: string; checks: Check[] }
export interface StagesDoc {
  version: number; generated_at: string; week: string; rules: Record<string, number>; screens: Record<string, string>;
  finviz_totals: Record<string, { total: number; read: number }>; skipped: Record<string, number>;
  pre_he: Record<string, string>; buy_stop_candidates?: unknown[]; sell_stop_candidates?: unknown[]; market_gate?: { ok: boolean | null; he: string }; short_market_gate?: { ok: boolean | null; he: string }; market: Record<string, EtfStage>; sectors: Record<string, EtfStage>; industries?: Record<string, EtfStage>; strong_sectors: string[]; weak_sectors?: string[]; strong_industries?: string[]; weak_industries?: string[]; counts: Record<string, number>; rows: StageRow[];
}
/** fundamental overviews (Supabase ticker_research, filled by main.ts) -- Buy-Stop candidates (Eyal 2026-11-14) */
export const stResearch = new Map<string, Research>();
export const isShortSide = (r: StageRow) => !r.plan && (!!r.short_plan || r.stage === 3 || r.stage === 4);
function rsLine(r: StageRow): string {
  if (!r.bs && !r.ss) return '';
  const x = stResearch.get(r.t), sh = x?.data?.short_he as string | undefined;
  return sh ? `<div class="strs small" title="סקירה פונדמנטלית ${esc(x?.data?.as_of ?? '')}">📊 ${isoLtr(sh)}</div>` : '<div class="strs small muted">📊 סקירה פונדמנטלית: עוד לא נאספה</div>';
}
export interface StSpark { w0: string; lo: number; hi: number; n: number; q: string; ma: string }

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const f = (x: unknown, d = 2) => (x == null || x === '' || Number.isNaN(+x!) ? '—' : (+x!).toFixed(d));
const sg = (x: number | null | undefined, d = 1) => (x == null ? '—' : (x > 0 ? '+' : '') + x.toFixed(d));
const ddmm = (iso?: string | null) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '—');

export const STAGE_HE: Record<number, string> = { 1: 'שלב 1 · בסיס', 2: 'שלב 2 · עלייה', 3: 'שלב 3 · פסגה', 4: 'שלב 4 · ירידה' };
export const SUB_HE: Record<string, string> = {
  '2A': 'פריצה חדשה (2A)', '2': 'מגמה עולה', '2-ext': 'מתוחה מעל הממוצע (>35%)', '2-weak': 'מתחת לממוצע עולה (אזהרה)',
  '1A': 'בסיס מוקדם (<10 ש׳)', '1': 'בסיס', '1T': 'סוף שלב 1 · נקודת מפנה', '2-dip': 'מתחת לממוצע עולה, שפל עולה מחזיק', '1B': 'בסיס בוגר (≥10 ש׳)', '3': 'פסגה / הפצה', '4A': 'שבירה חדשה (4A)', '4': 'מגמת ירידה', '4-ext': 'מתוחה מתחת לממוצע (>35%)', '4-late': 'מעל ממוצע יורד (אולי תחילת שלב 1)',
};
const CONF_HE: Record<string, string> = { high: 'ודאות גבוהה', med: 'ודאות בינונית', low: 'ודאות נמוכה' };
export type Tab = 'bs' | 'ss' | '2A' | '4A' | '1' | '2' | '3' | '4' | 'novol';
export const ACTION_TABS: [Tab, string][] = [['bs', 'מועמדות ל-Buy-Stop'], ['ss', 'מועמדי שורט (Sell-Stop)'], ['2A', 'פריצה לשלב 2 (חדשה)'], ['4A', 'שבירה לשלב 4 (4A)'], ['novol', 'פריצה בלי מחזור']];
export const STAGE_TABS: [Tab, string][] = [['1', 'שלב 1'], ['2', 'שלב 2'], ['3', 'שלב 3'], ['4', 'שלב 4']];
export const TABS: [Tab, string][] = [...ACTION_TABS.slice(0, 4), ...STAGE_TABS, ACTION_TABS[4]];
export const SORTS: [string, string][] = [['rs', 'RS מנספילד'], ['rr', 'R:R'], ['sl_asc', 'SL% נמוך → גבוה'], ['sl_desc', 'SL% גבוה → נמוך'], ['vol', 'מחזור פריצה'], ['pct_ma', '% מהממוצע'], ['slope', 'שיפוע'], ['score', 'ודאות'], ['near', 'קרבה לפריצה'], ['t', 'סימול']];

export interface UiState { tab: Tab; q: string; sort: string; pre: boolean; ready: boolean; conf: 'all' | 'med' | 'high'; near: boolean; starred?: boolean; rulesOpen?: boolean; lastT?: string }
export const UI_DEF: UiState = { tab: 'bs', q: '', sort: 'rs', pre: false, ready: false, conf: 'all', near: false, starred: false };

/** His edits on the stages page (public.stage_drawings): kind 'zone' = base ceiling / floor, 'long' = the trade bar. */
export interface StDraw { id: string; ticker: string; kind: 'zone' | 'long' | 'line'; zone_top: number | null; zone_bottom: number | null; entry: number | null; stop: number | null; target: number | null; t_start: string | null; t_end: string | null; source: 'user'; status: 'active' | 'deleted'; meta?: Record<string, any> | null; updated_at?: string; created_at?: string }
export interface StEd { zone?: StDraw; long?: StDraw; lines?: StDraw[] }
export type StEdits = Map<string, StEd>;

/** Levels behind the trade plan: the overhead resistances of the last 2 years (nearest = target; not drawn) and the
 *  stop-basis support (drawn as the red line, Eyal 2026-11-14). His rows (kind 'line') move (meta.ref = the computed
 *  id), hide (meta.hidden) or add (meta.role) a level. */
export interface StLevel { id: string; price: number; role: 'res' | 'sup' | 'cong'; label: string; his: boolean; ref?: string }
export function levelsOf(r: StageRow, ed?: StEd): StLevel[] {
  const comp: StLevel[] = [];
  if (isShortSide(r)) {
    const sp = r.short_plan;
    const sups = sp?.sup_levels?.length ? sp.sup_levels : sp?.support != null ? [sp.support] : [];
    sups.forEach((v, i) => comp.push({ id: 'c-sup' + i, price: v, role: 'sup', label: i === 0 ? 'תמיכה מטה (יעד)' : 'תמיכה מטה', his: false }));
    comp.push({ id: 'c-res', price: sp?.swing_high ?? r.ma30, role: 'res', label: sp?.swing_high != null ? 'התנגדות – שיא הפסגה' : 'התנגדות – 30W SMA', his: false });
  } else {
    const p = r.plan;
    const ov = p?.ov_levels?.length ? p.ov_levels : p?.overhead != null ? [p.overhead] : [];
    ov.forEach((v, i) => comp.push({ id: 'c-ov' + i, price: v, role: 'res', label: i === 0 ? 'התנגדות תקורה (יעד)' : 'התנגדות תקורה', his: false }));
    comp.push({ id: 'c-sup', price: p?.swing_low ?? r.ma30, role: 'sup', label: p?.swing_low != null ? 'תמיכה – שפל הבסיס' : 'תמיכה – 30W SMA', his: false });
  }
  const mine = (ed?.lines || []).filter((x) => x.status !== 'deleted');
  const over = new Map(mine.filter((x) => x.meta?.ref).map((x) => [x.meta!.ref as string, x]));
  const out: StLevel[] = [];
  for (const c of comp) {
    const o = over.get(c.id);
    if (!o) out.push(c);
    else if (!o.meta?.hidden && o.entry != null) out.push({ ...c, id: o.id, price: +o.entry, his: true, ref: c.id, label: c.label + ' (שלך)' });
  }
  for (const x of mine) if (!x.meta?.ref && !x.meta?.hidden && x.entry != null) {
    const role = (x.meta?.role as StLevel['role']) || 'res';
    out.push({ id: x.id, price: +x.entry, role, label: role === 'sup' ? 'תמיכה (שלך)' : 'התנגדות (שלך)', his: true });
  }
  return out;
}

/** Trade levels in force (long or short). */
export interface EffPlan { side: 'long' | 'short'; entry: number; stop: number; target: number | null; rr: number | null; slPct: number | null; shares: number | null; wide: boolean; his: boolean; basis: string; openSky?: boolean; overhead?: number | null; support?: number | null }
export function effPlan(r: StageRow, ed: StEd | undefined, maxRisk: number, maxStopPct = 10, R: Record<string, number> = {}): EffPlan | null {
  const L = ed?.long;
  const rv = (k: string, d: number) => (R[k] != null ? +R[k] : d);
  const shortSide = L?.entry != null && L?.stop != null ? (+L.stop > +L.entry) : isShortSide(r);
  const done = (entry: number, stop: number, target: number | null, his: boolean, basis: string, openSky?: boolean, overhead?: number | null, support?: number | null): EffPlan => {
    const risk = shortSide ? (stop - entry) : (entry - stop);
    const rr = target != null && risk > 0 && (shortSide ? (target > 0 && target < entry) : (target > entry)) ? (shortSide ? (entry - target) : (target - entry)) / risk : null;
    const slPct = entry ? (risk / entry) * 100 : null;
    return { side: shortSide ? 'short' : 'long', entry, stop, target, rr, slPct, shares: risk > 0 ? Math.floor(maxRisk / risk) : null, wide: slPct != null && slPct > maxStopPct, his, basis, openSky, overhead, support };
  };
  if (L?.entry != null && L.stop != null) return done(+L.entry, +L.stop, L.target == null ? null : +L.target, true, 'שלך');
  const linesEd = (ed?.lines || []).some((x) => x.status !== 'deleted');
  if (!linesEd && !ed?.zone) {
    if (shortSide) {
      const sp = r.short_plan; if (!sp) return null;
      return done(+sp.entry, +sp.stop, sp.target == null ? null : +sp.target, false, BASIS_HE[sp.stop_basis] ?? 'ממוצע', sp.open_sky, null, sp.support);
    }
    const p = r.plan; if (!p) return null;
    return done(+p.entry, +p.stop, p.target == null ? null : +p.target, false, BASIS_HE[p.stop_basis] ?? 'ממוצע', p.open_sky, p.overhead);
  }
  const lv = levelsOf(r, ed);
  if (shortSide) {
    const sp = r.short_plan;
    let entry = sp?.entry != null ? +sp.entry : null;
    if (ed?.zone?.zone_bottom != null) { const z = +ed.zone.zone_bottom; entry = Math.max(0.01, Math.round((z - Math.max(z * rv('sell_stop_buf_pct', 0.5) / 100, rv('sell_stop_min_buf', 0.05))) * 100) / 100); }
    if (entry == null) return null;
    const res = lv.filter((x) => x.role === 'res' && x.price > entry!).sort((a, b) => a.price - b.price);
    const B = res[0];
    const high = B != null && B.price > r.ma30;
    const stop = stopAbove(high ? B!.price : r.ma30, R);
    const basis = high ? (B!.his ? 'התנגדות שלך' : 'שיא') : 'ממוצע';
    const sups = lv.filter((x) => x.role === 'sup' && x.price > 0 && x.price < entry! * (1 - rv('target_min_gap_pct', 2) / 100)).sort((a, b) => b.price - a.price);
    const risk = stop - entry;
    const tSky = risk > 0 ? entry - rv('min_rr', 2.5) * risk : null;
    const target = sups.length ? sups[0].price : (tSky != null && tSky > 0 ? tSky : null);
    return done(entry, Math.round(stop * 100) / 100, target == null ? null : Math.round(target * 100) / 100, true, basis, !sups.length, null, sups[0]?.price ?? null);
  }
  const p = r.plan;
  let entry = p?.entry != null ? +p.entry : null;
  if (ed?.zone?.zone_top != null) { const z = +ed.zone.zone_top; entry = Math.round((z + Math.max(z * rv('buy_stop_buf_pct', 0.5) / 100, rv('buy_stop_min_buf', 0.05))) * 100) / 100; }
  if (entry == null) return null;
  const sups = lv.filter((x) => x.role === 'sup' && x.price < entry!).sort((a, b) => b.price - a.price);
  const B = sups[0];
  const low = B != null && B.price < r.ma30;
  const stop = stopBelow(low ? B!.price : r.ma30, R);
  const basis = low ? (B!.his ? 'תמיכה שלך' : 'שפל') : 'ממוצע';
  const res = lv.filter((x) => x.role === 'res' && x.price > entry! * (1 + rv('target_min_gap_pct', 2) / 100)).sort((a, b) => a.price - b.price);
  const risk = entry - stop;
  const target = res.length ? res[0].price : risk > 0 ? entry + rv('min_rr', 2.5) * risk : null;
  return done(entry, Math.round(stop * 100) / 100, target == null ? null : Math.round(target * 100) / 100, true, basis, !res.length, res[0]?.price ?? null);
}
export const BASIS_HE: Record<string, string> = { ma: 'ממוצע', low: 'שפל', hl: 'שפל עולה', high: 'שיא', lh: 'שיא יורד' };
/** Stop under an anchor (Eyal 2026-11-16, mirror of srs_app.stages.stop_below): 0.75% under it, or just ($0.05) under a
 *  round number sitting just under it when that stays within 1% of the anchor. */
export function stopBelow(anchor: number, R: Record<string, number> = {}): number {
  const rv = (k: string, d: number) => (R[k] != null ? +R[k] : d);
  let stop = anchor * (1 - rv('stop_margin_pct', 0.75) / 100);
  const st = anchor < 10 ? 0.5 : anchor < 100 ? 1 : anchor < 1000 ? 5 : 10;
  let rn = Math.floor(anchor / st) * st; if (rn >= anchor) rn = anchor;
  const alt = rn - rv('stop_round_tick', 0.05);
  if (alt >= anchor * (1 - rv('stop_margin_max_pct', 1) / 100) && alt < stop) stop = alt;
  return stop;
}
/** Protective Buy-Stop above an anchor (mirror of stopBelow). */
export function stopAbove(anchor: number, R: Record<string, number> = {}): number {
  const rv = (k: string, d: number) => (R[k] != null ? +R[k] : d);
  let stop = anchor * (1 + rv('stop_margin_pct', 0.75) / 100);
  const st = anchor < 10 ? 0.5 : anchor < 100 ? 1 : anchor < 1000 ? 5 : 10;
  let rn = Math.ceil(anchor / st) * st; if (rn <= anchor) rn = anchor;
  const alt = rn + rv('stop_round_tick', 0.05);
  if (stop < alt && alt <= anchor * (1 + rv('stop_margin_max_pct', 1) / 100)) stop = alt;
  return stop;
}
/** Computed base ceiling / floor shown as the editable zone. */
export function zoneOf(r: StageRow): { top: number; bottom: number; start: string | null } | null {
  if (r.bo && r.sub === '2A') return { top: r.bo.level, bottom: r.bo.base_low, start: r.bo.res_week ?? null };
  if (r.base) return { top: r.base.top, bottom: r.base.low, start: r.base.top_week ?? r.range?.since ?? null };
  if (r.bd && r.sub === '4A') return { top: r.bd.base_high, bottom: r.bd.level, start: r.bd.sup_week ?? null };
  if (r.short_base) return { top: r.short_base.top, bottom: r.short_base.floor, start: r.short_base.bot_week ?? r.range?.since ?? null };
  if (r.range?.ceil != null && r.range.floor != null) return { top: r.range.ceil, bottom: r.range.floor, start: r.range.since };
  return null;
}

export function inTab(r: StageRow, tab: Tab): boolean {
  if (tab === 'bs') return !!r.bs;
  if (tab === 'ss') return !!r.ss;
  if (tab === '2A') return r.sub === '2A';
  if (tab === '4A') return r.sub === '4A';
  if (tab === 'novol') return !!r.bo && r.bo.holding && !r.bo.vol_ok && !r.bo.in_range;
  return String(r.stage) === tab;
}
export function filterRows(rows: StageRow[], ui: UiState, edits?: StEdits, maxRisk = 55, maxStopPct = 10, watched?: { has(t: string): boolean }): StageRow[] {
  const q = ui.q.trim().toUpperCase();
  let out = rows.filter((r) => inTab(r, ui.tab));
  if (q) out = out.filter((r) => r.t.includes(q) || (r.n || '').toUpperCase().includes(q) || (r.sec || '').toUpperCase().includes(q) || (r.ind || '').toUpperCase().includes(q) || (r.etf || '') === q);
  if (ui.pre) out = out.filter((r) => r.pre_ok);
  if (ui.ready) out = out.filter((r) => isShortSide(r) ? !!r.short_entry_ok : r.entry_ok);
  if (ui.starred) out = out.filter((r) => !!watched?.has(r.t));
  if (ui.conf === 'high') out = out.filter((r) => r.conf === 'high');
  if (ui.conf === 'med') out = out.filter((r) => r.conf !== 'low');
  if (ui.near) out = out.filter((r) => (r.base && r.base.dist_pct <= 5) || (r.short_base && r.short_base.dist_pct <= 5));
  const ep = (r: StageRow) => effPlan(r, edits?.get(r.t), maxRisk, maxStopPct);
  const key = (r: StageRow): number | string => {
    switch (ui.sort) {
      case 'rr': return ep(r)?.rr ?? -1e9;
      case 'sl_asc': { const v = ep(r)?.slPct; return v == null || v <= 0 ? -1e9 : -v; }
      case 'sl_desc': { const v = ep(r)?.slPct; return v == null || v <= 0 ? -1e9 : v; }
      case 'vol': return r.bo?.vol_ratio ?? r.bd?.vol_ratio ?? -1e9;
      case 'pct_ma': return r.pct_ma ?? -1e9;
      case 'slope': return r.slope ?? -1e9;
      case 'score': return r.score * 1000 + (r.rs ?? 0);
      case 'near': return -(r.base?.dist_pct ?? r.bo?.pct_above ?? r.short_base?.dist_pct ?? (r.bd?.pct_below != null ? -r.bd.pct_below : null) ?? 1e9);
      case 't': return r.t;
      default: return r.rs ?? -1e9;
    }
  };
  out.sort((a, b) => { const x = key(a), y = key(b); return typeof x === 'string' ? x.localeCompare(y as string) : (y as number) - (x as number); });
  return out;
}

const chk = (c: Check) => `<li class="${c.info ? 'unk' : c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'unk'}"><span class="ci">${c.info ? 'ℹ' : c.ok === true ? '✓' : c.ok === false ? '✗' : '?'}</span>${esc(c.he)}</li>`;
export const stageBadge = (s: number, sub?: string) => `<span class="badge st st${s}">${esc(STAGE_HE[s] || 'שלב ' + s)}${sub ? ' · ' + esc(SUB_HE[sub] || sub) : ''}</span>`;
/** Gate ETF (industry when mapped) + the broad sector when both exist (sector is then info only). */
export function etfBadges(r: StageRow, asLink = false): string {
  const one = (tk: string | null | undefined, st: number | null | undefined, title: string, info = false) => {
    if (!tk) return '';
    const cls = `badge etfl st${st ?? 0}${info ? ' b-off' : ''}`;
    return asLink
      ? ` · <a class="${cls}" data-etf="${esc(tk)}" href="#/stages/${esc(tk)}" title="${esc(title)}">${esc(tk)} שלב ${st ?? '?'}</a>`
      : ` <button class="${cls}" data-etf="${esc(tk)}" title="${esc(title)}" dir="ltr">${esc(tk)}</button>`;
  };
  const ind = r.ind_etf, sec = r.sec_etf;
  if (ind && sec && ind !== sec) return one(ind, r.etf_stage, 'ענף (שער כניסה)') + one(sec, r.sec_etf_stage, 'סקטור (מידע)', true);
  return one(r.etf, r.etf_stage, ind ? 'ענף (שער כניסה)' : 'סקטור');
}


const ETF_NASDAQ = new Set(['QQQ', 'SMH', 'IGV', 'ITA', 'IBB', 'ITB', 'IHI', 'IYT', 'CIBR', 'SKYY', 'BOTZ', 'TAN', 'COPX', 'URA', 'LIT']);
export function tvUrl(r: Pick<StageRow, 't' | 'ex'>) { return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent((r.ex || '') + ':' + r.t.replace('-', '.'))}&interval=W`; }

const kv = (k: string, v: string, cls = '') => `<div class="skv ${cls}"><span>${k}</span><b dir="ltr">${v}</b></div>`;
const earnTxt = (r: StageRow) => (r.earn ? `${ddmm(r.earn)}${r.earn_est ? ' משוער' : ''}${r.earn_timing === 'a' ? ' אחה״ס' : r.earn_timing === 'b' ? ' לפנ״פ' : ''}${r.earn_td != null ? ` · בעוד ${r.earn_td} ימ״ס` : ''}` : 'לא ידוע');
const earnBad = (r: StageRow) => (r.earn_block ? 'neg' : '');
const dvTxt = (m: number | null | undefined) => (m == null || Number.isNaN(+m) ? '—' : +m >= 1000 ? '$' + (+m / 1000).toFixed(1) + 'B' : '$' + f(m, 1) + 'M');

/** overhead resistance (long) or downside support (short) in force */
function ovOf(r: StageRow, e: EffPlan | null): { sky: boolean; lv: number | null; pct: number | null; his: boolean } {
  const p = r.plan;
  if (e?.his && e.openSky != null) return { sky: e.openSky, lv: e.overhead ?? null, pct: e.overhead != null ? (e.overhead / e.entry - 1) * 100 : null, his: true };
  return { sky: !!p?.open_sky, lv: p?.overhead ?? null, pct: p?.overhead_pct ?? null, his: false };
}
function supOf(r: StageRow, e: EffPlan | null): { sky: boolean; lv: number | null; pct: number | null; his: boolean } {
  const sp = r.short_plan;
  if (e?.his && e.openSky != null) return { sky: e.openSky, lv: e.support ?? null, pct: e.support != null ? (1 - e.support / e.entry) * 100 : null, his: true };
  return { sky: !!sp?.open_sky, lv: sp?.support ?? null, pct: sp?.support_pct ?? null, his: false };
}
/** tags of a stock: Buy-Stop / Sell-Stop candidate, open sky / target level, don't chase, SL too wide, earnings, his levels */
export function tagsHtml(r: StageRow, e: EffPlan | null, hisZone = false): string {
  const t: string[] = [];
  if (isShortSide(r)) {
    const sp = r.short_plan;
    if (r.ss) t.push('<span class="badge b-short">מועמדת לשורט (Sell-Stop)</span>');
    const sup = supOf(r, e);
    if (sup.sky) t.push(`<span class="badge b-sky">שמיים פתוחים מטה${sup.his ? ' (שלך)' : sp?.atl ? ' · ATL' : ''}</span>`);
    else if (sup.lv != null) t.push(`<span class="badge b-off" title="תמיכה קרובה מטה">תמיכה מטה${sup.his ? ' (שלך)' : ''} $${f(sup.lv)} (-${f(sup.pct, 1)}%)</span>`);
    if (sp?.chase || (!sp && r.stage === 4 && (r.pct_ma ?? 0) < -25)) t.push('<span class="badge b-fail">רחוקה מדי / אל תרדוף</span>');
    if (e?.wide) t.push('<span class="badge b-fail">SL רחב מדי</span>');
    if (r.earn_block) t.push(`<span class="badge b-fail">דוח בעוד ${r.earn_td} ימ״ס${r.earn_est ? ' (משוער)' : ''} – לא להציב Sell-Stop</span>`);
    if (r.post_gap_short) t.push('<span class="badge b-fail">גאפ מטה אחרי דוח – לא לרדוף</span>');
    else if (r.post_earn_short && r.post_earn_short.startsWith('דוח עבר') && r.post_earn_short.includes('להחזיר')) t.push('<span class="badge b-short">דוח עבר – להחזיר Sell-Stop</span>');
    if (r.short_float != null && r.short_float >= 10) t.push(`<span class="badge b-fail">שורט פלואט ${f(r.short_float, 1)}%</span>`);
    if (e?.his || hisZone) t.push('<span class="badge b-his">הרמות שלך</span>');
    if (!r.pre_ok) t.push('<span class="badge b-off">נפסלת בסינון המקדים</span>');
    return t.join('');
  }
  const p = r.plan;
  if (r.bs) t.push('<span class="badge b-pass">מועמדת ל-Buy-Stop</span>');
  const ov = ovOf(r, e);
  if (ov.sky) t.push(`<span class="badge b-sky">שמיים פתוחים${ov.his ? ' (שלך)' : p?.ath ? ' · ATH' : ''}</span>`);
  else if (ov.lv != null) t.push(`<span class="badge b-off" title="התנגדות תקורה">תקורה${ov.his ? ' (שלך)' : ''} $${f(ov.lv)} (+${f(ov.pct, 1)}%)</span>`);
  if (p?.chase || (!p && r.stage === 2 && (r.pct_ma ?? 0) > 25)) t.push('<span class="badge b-fail">רחוקה מדי / אל תרדוף</span>');
  if (e?.wide) t.push('<span class="badge b-fail">SL רחב מדי</span>');
  if (r.earn_block) t.push(`<span class="badge b-fail">דוח בעוד ${r.earn_td} ימ״ס${r.earn_est ? ' (משוער)' : ''} – לא להציב Buy-Stop</span>`);
  if (r.post_gap) t.push('<span class="badge b-fail">גאפ אחרי דוח – לא לרדוף</span>');
  else if (r.post_earn && r.post_earn.startsWith('דוח עבר') && r.post_earn.includes('להחזיר')) t.push('<span class="badge b-pass">דוח עבר – להחזיר Buy-Stop</span>');
  if (e?.his || hisZone) t.push('<span class="badge b-his">הרמות שלך</span>');
  if (!r.pre_ok) t.push('<span class="badge b-off">נפסלת בסינון המקדים</span>');
  return t.join('');
}

function cardInnerHtml(r: StageRow, e: EffPlan | null, hisZone = false, watched = false): string {
  const shortSide = isShortSide(r);
  const srcEntry = shortSide ? (r.short_entry || []) : r.entry;
  const gates = srcEntry.filter((c) => !c.info), n = gates.length, ok = gates.filter((c) => c.ok === true).length;
  return `<div class="r1"><button class="star ${watched ? 'on' : ''}" data-star="${esc(r.t)}" aria-label="מעקב">${watched ? '★' : '☆'}</button><b class="sttk" dir="ltr">${esc(r.t)}</b> ${stageBadge(r.stage, r.sub)} <span class="badge conf-${r.conf}" title="${r.score}/4 תנאי זיהוי">${r.score}/4</span>${etfBadges(r)}</div>
  <div class="sttags">${tagsHtml(r, e, hisZone)}</div>${rsLine(r)}
  <div class="stchartwrap"><canvas class="stchart" data-stchart="${esc(r.t)}" aria-label="גרף שבועי שנתיים + 30W SMA"></canvas><div class="atrw"${r.atr_w == null ? ' hidden' : ''}><span>ATR(W)</span><b>${r.atr_w == null ? '' : r.atr_w.toFixed(2)}</b></div></div>
  <div class="skvs">
    ${kv('R:R', e?.rr != null ? '1:' + f(e.rr) : '—', e?.rr != null && e.rr >= 2.5 ? 'pos' : 'neg')}${kv('SL', e?.slPct != null ? `${f(e.slPct, 1)}% · ${e.basis}` : '—', e ? (e.wide ? 'neg' : 'pos') : '')}
    ${kv('מניות ($55)', e?.shares ? String(e.shares) : '—')}${kv('תנאי כניסה', n ? `${ok}/${n}` : '—', n ? (ok === n ? 'pos' : 'neg') : '')}
    ${kv(shortSide ? 'Sell-Stop' : 'Buy-Stop', e ? '$' + f(e.entry) : '—')}${kv('דוח', earnTxt(r), earnBad(r))}
    ${kv('מחזור יומי', dvTxt(r.dv_m))}${shortSide && r.short_float != null ? kv('שורט פלואט', `${f(r.short_float, 1)}%`, r.short_float >= 10 ? 'neg' : '') : ''}
  </div>`;
}

/** One stock in the side list (like the retest list): ticker + stage + tags, mini chart, R:R / SL% / shares / rules. */
export function rowHtml(r: StageRow, e: EffPlan | null, sel: boolean, hisZone = false, watched = false): string {
  return `<li class="row strow2${sel ? ' sel' : ''}" data-st="${esc(r.t)}">${cardInnerHtml(r, e, hisZone, watched)}</li>`;
}

export function listHtml(d: StagesDoc, ui: UiState, rows: StageRow[], edits: StEdits, maxRisk: number, limit: number, selT: string | null, watched?: { has(t: string): boolean }): string {
  const cnt = (t: Tab) => d.rows.filter((r) => inTab(r, t)).length;
  const ms = +(d.rules.max_stop_pct ?? 10);
  const shortRows = ui.tab === 'bs' ? filterRows(d.rows, { ...ui, tab: 'ss' }, edits, maxRisk, ms, watched) : [];
  const shortSec = ui.tab === 'bs' ? `<section class="stshortsec" id="stshortsec">
    <div class="stshorthead"><h3>מועמדי שורט (Sell-Stop) <span class="cnt">${shortRows.length}</span></h3><span class="small muted">${esc(d.short_market_gate?.he ?? '')}</span></div>
    ${shortRows.length ? `<div class="list stlist2">${shortRows.slice(0, limit).map((r) => `<div class="row strow2 stshortcard${r.t === selT ? ' sel' : ''}" data-stshort="${esc(r.t)}">${cardInnerHtml(r, effPlan(r, edits.get(r.t), maxRisk, ms, d.rules), !!edits.get(r.t)?.zone || !!edits.get(r.t)?.lines?.length, !!watched?.has(r.t))}</div>`).join('')}</div>`
      : `<div class="center muted stshortempty">${ui.starred ? 'אין מועמדות לשורט במעקב השבוע' : 'אין השבוע מניה שעוברת את כל הכללים ל-Sell-Stop'}</div>`}
  </section>` : '';
  return `<header class="top"><a id="stHome" class="ghost btnlike small" href="#/">→ Retest</a><div class="title">שלבי ויינשטיין <span class="muted small">${ddmm(d.week)}</span></div>
    <div class="hbtns"><button id="strulesBtn" class="ghost small">כללים</button></div></header>
  <div class="sttabs">
      <div class="chips sttabs-stages" role="tablist" aria-label="סינון לפי שלב">${STAGE_TABS.map(([t, he]) => `<button class="chip ${ui.tab === t ? 'on' : ''}" data-tab="${t}">${he} <span class="cnt">${cnt(t)}</span></button>`).join('')}</div>
      <div class="chips sttabs-actions" role="tablist">${ACTION_TABS.map(([t, he]) => `<button class="chip ${ui.tab === t ? 'on' : ''}" data-tab="${t}">${he} <span class="cnt">${cnt(t)}</span></button>`).join('')}</div>
    </div>
  <div class="stfilters">
    <div class="stfilters-more">
    <div class="strow"><input id="stq" type="search" placeholder="חיפוש סימול / חברה / סקטור" value="${esc(ui.q)}" />
      <label class="sortlab">מיון <select id="stsort">${SORTS.map(([k, he]) => `<option value="${k}" ${ui.sort === k ? 'selected' : ''}>${he}</option>`).join('')}</select></label></div>
    <div class="chips">
      <button class="chip ${ui.pre ? 'on' : ''}" data-tg="pre">עוברות סינון מקדים</button>
      <button class="chip ${ui.starred ? 'on' : ''}" data-tg="starred">★ במעקב בלבד</button>
      <button class="chip ${ui.ready ? 'on' : ''}" data-tg="ready">כל תנאי הכניסה</button>
      <button class="chip ${ui.conf === 'med' ? 'on' : ''}" data-conf="med">ודאות ≥3/4</button>
      <button class="chip ${ui.conf === 'high' ? 'on' : ''}" data-conf="high">ודאות 4/4</button>
      ${ui.tab === '1' || ui.tab === '3' ? `<button class="chip ${ui.near ? 'on' : ''}" data-tg="near">${ui.tab === '3' ? 'עד 5% מתחתית הבסיס' : 'עד 5% מתקרת הבסיס'}</button>` : ''}
      <button class="chip" id="stcopy">העתק ל-TradingView</button>
    </div>
    <div class="small muted" id="stcount">${rows.length} מניות · עודכן ${new Date(d.generated_at).toLocaleString('he-IL', { timeZone: 'Asia/Jerusalem', dateStyle: 'short', timeStyle: 'short' })}</div>
    ${topDownHtml(d)}
    </div>
  </div>
  <div class="stresults">
  <ul class="list stlist2">${rows.slice(0, limit).map((r) => rowHtml(r, effPlan(r, edits.get(r.t), maxRisk, ms, d.rules), r.t === selT, !!edits.get(r.t)?.zone || !!edits.get(r.t)?.lines?.length, !!watched?.has(r.t))).join('') || `<li class="center muted">${ui.tab === 'bs' && !ui.starred ? 'אין השבוע מניה שעוברת את כל הכללים ל-Buy-Stop' : ui.tab === 'ss' && !ui.starred ? 'אין השבוע מניה שעוברת את כל הכללים ל-Sell-Stop' : ui.starred ? 'אין מניות במעקב בלשונית הזו' : 'אין מניות ברשימה הזו'}</li>`}
  ${rows.length > limit ? `<li class="center"><button id="stmore" class="ghost">הצג עוד (${rows.length - limit})</button></li>` : ''}</ul>${shortSec}</div>`;
}

/** Selected stock: big weekly chart (editable base ceiling / floor + trade bar) + plan + checks. */
export function detailHtml(d: StagesDoc, r: StageRow, e: EffPlan | null, ed: StEd | undefined, maxRisk: number, selLine: StLevel | null = null, watched = false): string {
  const shortSide = isShortSide(r);
  const p = r.plan, sp = r.short_plan, bo = r.bo, bd = r.bd, z = ed?.zone, zc = zoneOf(r);
  const R = d.rules, minRr = +(R.min_rr ?? 2.5);
  const ceil = z?.zone_top ?? zc?.top, floor = z?.zone_bottom ?? zc?.bottom;
  const kindHe = shortSide
    ? (sp ? (sp.kind === 'breakdown' ? 'שבירה טרייה (4A) — Sell-Stop מתחת לרמת התמיכה' : sp.kind === 'continuation' ? 'בסיס המשך בשלב 4 — Sell-Stop מתחת לרצפה' : 'פסגת שלב 3 — Sell-Stop מתחת לרצפת הבסיס') : 'אין עסקת שורט מחושבת')
    : (p ? (p.kind === 'breakout' ? 'פריצה טרייה — Buy-Stop מעל רמת הפריצה (או Pullback אליה)' : p.kind === 'continuation' ? 'בסיס המשך בשלב 2 — Buy-Stop מעל התקרה' : 'בסיס שלב 1 — Buy-Stop מעל התקרה') : 'אין עסקה מחושבת (אפשר לשרטט עסקה בעצמך)');
  const baseChecks = shortSide ? (r.short_entry || []) : r.entry;
  const entryChecks = baseChecks.map((c) => {
    if (!e?.his) return c;
    if (c.k === 'rr') return { ...c, ok: e.rr != null && e.rr >= minRr, he: `R:R ≥ ${minRr} לפי הרמות שלך (1:${f(e.rr)})` };
    if (c.k === 'stop') return { ...c, ok: !e.wide, he: `מידע בלבד (לא פוסל): SL ${f(e.slPct, 1)}% לפי הרמות שלך${e.wide ? ' — SL רחב מדי' : ''}` };
    return c;
  });
  const toolsHint = shortSide
    ? 'קו אדום = התנגדות (בסיס ה-SL), קו כחול = תמיכה (רצפת הבסיס / Sell-Stop). גרור אותם או את ה-Sell-Stop / SL / יעד — נשמר כ"שלך" וגובר על החישוב'
    : 'קו אדום = תמיכה (בסיס ה-SL), קו כחול = התנגדות (תקרת הבסיס / Buy-Stop). גרור אותם או את ה-Buy-Stop / SL / יעד — נשמר כ"שלך" וגובר על החישוב (SL / R:R מחושבים מחדש)';
  return `<div class="cv stcv">
  <header class="top ch" id="chhead">
    <a id="stback" class="ghost icon btnlike" href="#/stages" aria-label="חזרה">→</a>
    <div class="tk"><button id="ststar" class="ghost icon star ${watched ? 'on' : ''}" data-star="${esc(r.t)}" aria-label="מעקב">${watched ? '★' : '☆'}</button><a class="sttk" href="${tvUrl(r)}" target="_blank" rel="noopener" dir="ltr"><b>${esc(r.t)}</b></a> <span class="muted small" dir="ltr">$${f(r.close)}</span> ${stageBadge(r.stage, r.sub)}
      <div class="small muted stname">${esc(r.n)} · ${esc(r.sec)} / ${esc(r.ind)}${etfBadges(r, true)}</div></div>
    <button id="stprev" class="ghost icon" aria-label="הקודם">‹</button><button id="stnext" class="ghost icon" aria-label="הבא">›</button>
  </header>
  <div class="sttags pad">${tagsHtml(r, e, !!ed?.zone || !!ed?.lines?.length)}</div>
  <div id="stbig" class="chartwrap" dir="ltr"><div id="stnodata" class="nodata" hidden>אין נרות שבועיים למניה הזו</div></div>
  <div class="tools"><span class="small muted">${toolsHint}</span>
    ${ed?.zone || ed?.long || ed?.lines?.length ? '<button id="streset" class="ghost small">חזרה לרמות המחושבות</button>' : ''}${!(shortSide ? sp : p) && !ed?.long ? '<button id="staddlong" class="ghost small">+ עסקה</button>' : ''}</div>
  <div class="panel stpanel">
    <div class="stplan"><b>${esc(kindHe)}</b>
      <div class="skvs">
        ${kv(e?.his ? (shortSide ? 'Sell-Stop (שלך)' : 'Buy-Stop (שלך)') : (shortSide ? 'Sell-Stop' : 'Buy-Stop'), e ? '$' + f(e.entry) : '—')}${kv('SL' + (e ? ` (${e.basis})` : ''), e ? `$${f(e.stop)} (${f(e.slPct, 1)}%)` : '—', e ? (e.wide ? 'neg' : 'pos') : '')}
        ${kv('יעד', e?.target != null ? '$' + f(e.target) + (e.his ? '' : (shortSide ? sp?.target_src : p?.target_src) === 'open_sky' ? ' · 2.5R' : shortSide ? ' · תמיכה' : ' · תקורה') : '—')}${kv('R:R', e?.rr != null ? '1:' + f(e.rr) : '—', e?.rr != null && e.rr >= minRr ? 'pos' : 'neg')}
        ${kv(`מניות בסיכון $${f(maxRisk, 0)}`, e?.shares ? `${e.shares} ($${f(e.shares * e.entry, 0)})` : '—')}${shortSide
          ? (() => { const sup = supOf(r, e); return kv('תמיכה מטה (שנתיים)' + (sup.his ? ' (שלך)' : ''), sp || sup.his ? (sup.sky ? 'אין — שמיים פתוחים מטה' : `$${f(sup.lv)} (-${f(sup.pct, 1)}%)`) : '—', sup.sky ? 'pos' : ''); })()
          : (() => { const ov = ovOf(r, e); return kv('התנגדות תקורה (שנתיים)' + (ov.his ? ' (שלך)' : ''), p || ov.his ? (ov.sky ? 'אין — שמיים פתוחים' : `$${f(ov.lv)} (+${f(ov.pct, 1)}%)`) : '—', ov.sky ? 'pos' : ''); })()}
        ${kv(z ? 'תקרת בסיס (שלך)' : 'תקרת בסיס', ceil != null ? '$' + f(ceil) : '—')}${kv(z ? 'רצפת בסיס (שלך)' : 'רצפת בסיס', floor != null ? '$' + f(floor) : '—')}
        ${shortSide ? kv('מהרצפה', floor != null ? `${sg((r.close / floor - 1) * 100)}%` : '—') : kv('מהתקרה', ceil != null ? `${sg((r.close / ceil - 1) * 100)}%` : '—')}${kv('מ-30W SMA', sg(r.pct_ma) + '%', shortSide ? ((r.pct_ma ?? 0) < -25 ? 'neg' : '') : ((r.pct_ma ?? 0) > 25 ? 'neg' : ''))}
        ${!shortSide && p?.vol_need ? kv('מחזור נדרש בשבוע הפריצה', Math.round(p.vol_need).toLocaleString('en-US')) : ''}${bo ? kv('מחזור פריצה', f(bo.vol_ratio, 1) + 'x', bo.vol_ok ? 'pos' : 'neg') : ''}${bd ? kv('מחזור שבירה', f(bd.vol_ratio, 1) + 'x') : ''}
        ${kv('דוח הבא', earnTxt(r), earnBad(r))}${r.earn_last ? kv('דוח אחרון', `${ddmm(r.earn_last)}${r.earn_last_ago != null ? ` · לפני ${r.earn_last_ago} ימ״ס` : ''}`) : ''}${kv('Mansfield RS', `${sg(r.rs)} ${r.rs_up == null ? '' : r.rs_up ? '↑' : '↓'}`, (r.rs ?? 0) > 0 ? 'pos' : 'neg')}
        ${kv('מחזור יומי' + ((R.dollar_vol_days != null) ? ` (${R.dollar_vol_days}י)` : ''), dvTxt(r.dv_m))}${kv('ATR(W)', r.atr_w != null ? '$' + f(r.atr_w) : '—')}${shortSide && r.short_float != null ? kv('שורט פלואט', `${f(r.short_float, 1)}%`, r.short_float >= 10 ? 'neg' : '') : ''}
      </div>
    </div>
    ${entryChecks.length ? `<h4>תנאי כניסה (${entryChecks.filter((c) => !c.info && c.ok === true).length}/${entryChecks.filter((c) => !c.info).length})</h4><ul class="cks">${entryChecks.map(chk).join('')}</ul>` : ''}
    ${stResearch.get(r.t) ? `<div class="strsfull">${researchHtml(stResearch.get(r.t), true)}</div>` : (r.bs || r.ss) ? '<p class="small muted">סקירה פונדמנטלית: עוד לא נאספה (נוצרת בשגרת השבת לכל מועמדת)</p>' : ''}
    <h4>זיהוי ${esc(STAGE_HE[r.stage])} (${r.score}/4)</h4><ul class="cks">${r.checks.map(chk).join('')}</ul>
    ${r.range ? `<p class="small muted">טווח השלב: $${f(r.range.floor)}–$${f(r.range.ceil)} · בשלב מאז ${ddmm(r.range.since)} (${r.range.since_w} ש׳) — בתוך טווח בסיס, חציית הממוצע לא משנה שלב.</p>` : ''}
    <h4>סינון מקדים</h4><ul class="cks">${r.pre.map((c) => chk({ ...c, he: c.he || d.pre_he?.[c.k] || c.k })).join('')}</ul>
    <p class="small muted">שבוע ${ddmm(r.week)} · ${r.weeks} שבועות נתונים · <a href="https://finviz.com/quote.ashx?t=${encodeURIComponent(r.t)}&p=w" target="_blank" rel="noopener">FinViz</a> · <a href="${tvUrl(r)}" target="_blank" rel="noopener">TradingView</a></p>
  </div></div>`;
}

const TD_CLS: Record<string, string> = { full: 'pos', turn: 'pos', early: 'pos', caution: 'warn', wait: 'neg', defend: 'neg', no_new: 'neg', avoid: 'neg', mkt_off: 'neg', na: '' };
const POS_HE: Record<string, string> = { above: 'מעל בעקביות', below: 'מתחת בעקביות', cross: 'חוצה הלוך ושוב' };
const SLOPE_HE = (s?: string) => (s === 'up' ? 'עולה' : s === 'down' ? 'יורד' : 'שטוח');
function etfPanel(title: string, entries: [string, EtfStage][], strong: string[]): string {
  const ok = entries.filter(([, e]) => e.sec_ok).map(([k]) => esc(k)).join(', ') || 'אין';
  const sok = entries.filter(([, e]) => e.short_sec_ok).map(([k]) => esc(k)).join(', ') || 'אין';
  const row = ([k, e]: [string, EtfStage]) => `<tr class="${strong.includes(k) ? 'strong' : ''}"><td dir="ltr"><a class="etfl" data-etf="${esc(k)}" href="#/stages/${esc(k)}"><b>${esc(k)}</b></a>${strong.includes(k) ? ' ★' : ''}</td><td>${esc(e.name)}</td><td>${stageBadge(e.stage, e.sub)}</td><td class="${e.sec_ok ? 'pos' : 'neg'}">${e.sec_ok ? '✓' : '✗'} ${esc(e.sec_he ?? '')}</td><td class="${e.short_sec_ok ? 'pos' : 'neg'}">${e.short_sec_ok ? '✓' : '✗'} ${esc(e.short_sec_he ?? '')}</td><td class="sectd ${TD_CLS[e.td ?? ''] ?? ''}">${esc(e.td_he ?? '')}</td><td>${esc(POS_HE[e.idx?.pos ?? ''] ?? '—')}${e.idx ? ` <span class="muted" dir="ltr">${e.idx.above_n}/${e.idx.of_w}</span>` : ''}</td><td dir="ltr">${SLOPE_HE(e.slope_cls)} ${sg(e.slope)}%</td><td dir="ltr">${esc(e.idx?.struct ?? '—')}</td><td dir="ltr">${sg(e.pct_ma)}%</td><td dir="ltr">${sg(e.rs)} ${e.rs_up == null ? '' : e.rs_up ? '↑' : '↓'}</td></tr>`;
  return `<details class="secs"><summary>${esc(title)} · לונג: ${ok} · שורט: ${sok}</summary>
  <div class="tbl"><table><tr><th>תעודה</th><th>שם</th><th>שלב</th><th>ללונג</th><th>לשורט</th><th>משמעות (Top-Down)</th><th>מחיר מול הממוצע</th><th>שיפוע</th><th>מבנה</th><th>מ-30W</th><th>RS (מידע)</th></tr>
  ${entries.map(row).join('')}
  </table></div></details>`;
}
export function topDownHtml(d: StagesDoc): string {
  const m = (k: string, e?: EtfStage) => e ? `<div class="mk"><a class="etfl" data-etf="${k}" href="#/stages/${k}" dir="ltr"><b>${k}</b></a> ${stageBadge(e.stage, e.sub)}<span class="small muted">RS <span dir="ltr">${sg(e.rs)}</span></span></div>` : '';
  const spy = d.market.SPY, mg = d.market_gate, smg = d.short_market_gate;
  const secs = Object.entries(d.sectors).sort((a, b) => (b[1].rs ?? -99) - (a[1].rs ?? -99));
  const inds = Object.entries(d.industries || {}).sort((a, b) => (b[1].rs ?? -99) - (a[1].rs ?? -99));
  return `<section class="topdown"><div class="mkts">${['SPY', 'QQQ', 'IWM'].map((k) => m(k, d.market[k])).join('')}</div>
  ${spy ? `<div class="mktd small ${mg?.ok === false ? 'neg' : TD_CLS[spy.idx?.td ?? ''] ?? ''}" id="mktd">${mg?.ok === false ? '⛔' : '🟢'} שוק (SPY) שלב ${spy.stage}: ${esc(spy.idx?.td_he ?? '')}${mg?.ok === false ? ' — אין Buy-Stop חדש' : ''}${d.market.QQQ ? ` · <span class="muted">QQQ שלב ${d.market.QQQ.stage} (מידע): ${esc(d.market.QQQ.idx?.td_he ?? '')}</span>` : ''}</div>` : ''}
  ${smg ? `<div class="mktd small ${smg.ok === false ? 'neg' : 'pos'}" id="shortmktd">${smg.ok === false ? '⛔' : '🔴'} ${esc(smg.he)}</div>` : ''}
  ${etfPanel('סקטורים', secs, d.strong_sectors)}
  ${etfPanel('ענפים', inds, d.strong_industries || [])}</section>`;
}

export function rulesHtml(d: StagesDoc, maxRisk: number): string {
  const R = d.rules;
  const scr = Object.entries(d.screens).map(([k, u]) => `<a href="${esc(u.replace('v=152', 'v=111'))}" target="_blank" rel="noopener">${k}</a>`).join(' · ');
  return `<div class="strules">
  <p><b>מקור:</b> דף המסטרקלאס של ויינשטיין ששלחת + הכללים שהוספת ב-14/11 (התנגדות תקורה, לא רודפים, Buy-Stop, דוחות, טווח בסיס, SL). נרות שבועיים בלבד (סגירת שישי, שבוע שהושלם).</p>
  <h4>יקום (FinViz)</h4><p>NYSE + NASDAQ, מניות בלבד, מחיר &gt; $${R.hard_min_price}, מחזור יומי ממוצע &gt; 100K. ${scr}.</p>
  <h4>סיווג השלב — לפי טווח המסחר (14/11)</h4><ul>
   <li>30W SMA = ממוצע ${R.ma_weeks} סגירות שבועיות. שיפוע = שינוי ב-${R.slope_lookback_w} שבועות: עולה &gt; +${R.slope_flat_pct}%, יורד &lt; −${R.slope_flat_pct}%, אחרת שטוח.</li>
   <li><b>בתוך טווח בסיס חציית הממוצע לא משנה שלב.</b> שלב 1 (בסיס אחרי ירידה) עובר לשלב 2 רק בסגירה שבועית מעל תקרת הטווח כשהממוצע שטוח/עולה, ולשלב 4 רק בסגירה מתחת לרצפת הטווח. אותו דבר בשלב 3 (פסגה אחרי עלייה).</li>
   <li>טווח שלב 1/3 = השיא והשפל מאז שהשלב התחיל (או מהשפל/שיא שסיים את המגמה הקודמת), ${R.min_base_w}–${R.range_max_w} שבועות.</li>
   <li>שלב 2 נשאר שלב 2 (גם בבסיס המשך) עד סגירה מתחת לרצפת הבסיס הנוכחי כשהממוצע כבר לא עולה (→3, או →4 כשהממוצע יורד), או עד שהממוצע משתטח בלי שיא 26 ש׳ חדש ${R.min_base_w} שבועות (→3). שלב 4 עובר לשלב 1 כשהממוצע מפסיק לרדת.</li>
   <li><b>Mansfield RS</b> = ((מניה / S&amp;P 500) / SMA${R.rs_ma_weeks} − 1) × 100. "עולה" = גבוה מלפני ${R.rs_rising_w} שבועות.</li></ul>
  <h4>שלב של מדד / תעודת סקטור (15/11) — 4 פרמטרים, גרף שבועי + 30W SMA</h4><ul>
   <li><b>מחיר מול הממוצע:</b> "מעל בעקביות" = ≥ ${R.idx_consistent_n} מ-${R.idx_consistent_w} הסגירות האחרונות מעל 30W SMA; "מתחת בעקביות" = ≤ ${(R.idx_consistent_w ?? 10) - (R.idx_consistent_n ?? 8)}; אחרת "חוצה הלוך ושוב".</li>
   <li><b>שיפוע:</b> כמו במניות (${R.slope_lookback_w} שבועות, ±${R.slope_flat_pct}%).</li>
   <li><b>מבנה:</b> שיאי / שפלי סווינג שבועיים (${R.idx_pivot_w} נרות מכל צד): HH/HL = שיאים ושפלים עולים, LH/LL = יורדים; סגירה מעל שיא הסווינג האחרון = HH בהתהוות, מתחת לשפל האחרון = השפל העולה נשבר.</li>
   <li><b>כלל 1 — השיפוע גובר על חצייה בודדת:</b> שלב 4 רק כשהממוצע יורד <b>וגם</b> סגירה מתחת לתמיכה משמעותית (שפל הסווינג האחרון / רצפת הטווח). סגירה מתחת לממוצע שעדיין עולה, כשהשפל העולה מחזיק = עדיין שלב 2 ("מתחת לממוצע עולה, שפל עולה מחזיק"). שלב 2→3 כשהממוצע מאבד את העלייה ואין שיא חדש ${R.idx_top_w} שבועות (או שהשפל העולה נשבר).</li>
   <li><b>כלל 2 — סוף שלב 1:</b> חזרה מעל 30W SMA שהשתטח אחרי ירידה = נקודת מפנה (מותר לקנות מובילות בסקטור). שלב 1→2: סגירה מעל תקרת הבסיס (שיא מאושר) כשהממוצע לא יורד, או ממוצע עולה + מעל בעקביות + HH/HL.</li>
   <li><b>כלל 3 — Top-Down:</b> שוק 2 + סקטור 2 = הקצאה מלאה; סקטור 4 = להימנע; סקטור 3 = אין לונג חדש; שוק בשלב 3/4 = אין Buy-Stop חדש גם אם המניה נראית טוב.</li>
   <li><b>ענפים (16/11):</b> תעודות ענף (KRE, ITA, XBI, IGV, SMH, CIBR וכו׳) מסווגות באותם 4 פרמטרים. המניה נשענת על תעודת הענף כשהתעשייה ממופת, אחרת על הסקטור הרחב. שניהם מוצגים בכרטיס ובעמוד.</li></ul>
  <h4>Buy-Stop (מועמדות)</h4><ul>
   <li>כניסה = Buy-Stop מעט מעל תקרת הבסיס: תקרה + ${R.buy_stop_buf_pct}% (מינימום $${R.buy_stop_min_buf}). שני מצבים: (א) לפני פריצה — בסיס בוגר (תקרה מלפני ≥${R.min_base_w} ש׳), סגירה עד ${R.pre_bo_pct}% מתחת לתקרה ומעל 30W SMA; (ב) פריצה טרייה (2A) שעדיין באזור הקנייה.</li>
   <li>פריצה (2A): סגירה מעל תקרת ${R.base_window_w} השבועות (שנקבעה לפני ≥${R.min_base_w} ש׳) וגם מעל תקרת טווח שלב 1, מחזור שבוע הפריצה ≥ ${R.vol_mult}x ממוצע ${R.vol_avg_w} שבועות (עליות בתוך הבסיס במחזור רגיל — לא נפסל). לפני פריצה: תנאי על הטריגר — שבוע הפריצה חייב מחזור ≥ ${R.vol_mult}x.</li>
   <li><b>לא רודפים:</b> עד ${R.buy_zone_pct}% מעל רמת הפריצה ועד ${R.max_pct_above_ma}% מעל 30W SMA (מחיר או Buy-Stop), אחרת "רחוקה מדי / אל תרדוף".</li>
   <li><b>SL (16/11):</b> שני עוגנים בגרף השבועי — A = 30W SMA, B = השפל המשמעותי האחרון בבסיס הנוכחי שלא נשבר (רצפת הבסיס). ה-SL מתחת <b>לנמוך מבין השניים</b>, ${R.stop_margin_pct}% מתחתיו (בתוך 0.5%–${R.stop_margin_max_pct}%), או $${R.stop_round_tick} מתחת למספר עגול שנמצא ממש מתחת לעוגן אם זה עדיין בתוך ${R.stop_margin_max_pct}%. שפל מעל הממוצע → מתחת לממוצע ("ממוצע"); שפל מתחת לממוצע → מתחת לשפל ("שפל"). אם ה-SL מתחת לשפל רחוק מ-${R.max_stop_pct}% והממוצע כבר עולה — מתחת לשפל העולה האחרון שלא נשבר (מתחת לממוצע) אם יש ("שפל עולה"). קו תמיכה שלך = עוגן B (גם מתחת לממוצע). SL מעל ${R.max_stop_pct}% = תג "SL רחב מדי" — מידע בלבד, לא פוסל; אפשר למיין לפי SL%.</li>
   <li><b>התנגדות תקורה:</b> שיאי סווינג משמעותיים (${R.sig_pivot_w} נרות מכל צד) ב-${R.overhead_w} השבועות האחרונים מעל הכניסה (+${R.target_min_gap_pct}%). הקרובה = היעד. אין = "שמיים פתוחים": יעד = כניסה + ${R.min_rr}×סיכון (R:R ${R.min_rr} בדיוק). R:R ≥ ${R.min_rr}.</li>
   <li><b>דוחות — לפני כניסה:</b> לא מציבים Buy-Stop חדש כשהדוח בתוך ${R.earn_td} ימי המסחר הקרובים (שבוע הדוח והשבוע שלפניו; דוח אחרי הסגירה נספר ליום המסחר הבא) — "דוח בעוד X ימי מסחר – לא להציב Buy-Stop". כש-FinViz מציג רק דוח שעבר: הדוח הבא משוער = האחרון + 13 שבועות ("משוער"), וגם הוא חוסם בתוך החלון. תאריך לא ידוע = לא עובר עד שבודקים.</li>
   <li><b>אחרי דוח (${R.post_earn_td} ימי מסחר):</b> גאפ למעלה (פתיחה ≥ ${R.gap_min_pct}% מעל הסגירה, סגירה מעל ההתנגדות, מחזור ≥ ${R.gap_vol_mult}x ממוצע ${R.gap_vol_avg_d} ימים) = "גאפ אחרי דוח – לא לרדוף, להמתין להחזקה/בסיס קטן"; חוזרת להיות מועמדת אחרי ≥ ${R.mini_base_d} ימי מסחר שכולם נסגרו מעל רמת הפריצה (בסיס קטן; נרות יומיים, אחרת סגירה שבועית). הדוח עבר והמחיר עדיין צמוד מתחת להתנגדות = "דוח עבר – להחזיר Buy-Stop".</li>
   <li><b>בתוך פוזיציה (הנחיה בלבד, אין מעקב פוזיציות):</b> נכנסת 3–4 שבועות לפני הדוח והמניה +10%–15% מעל הכניסה — אפשר להחזיק דרך הדוח ולהדק את הסטופ מתחת לשפל האחרון. סביב מחיר הכניסה בלי כרית — לצמצם חצי או לצאת לפני הדוח.</li>
      <li><b>שוק (SPY) לא בשלב 3 או 4</b> (כלל Top-Down, 15/11; QQQ מוצג כמידע); <b>ענף אם יש תעודה ממופת (CIBR / KRE / SMH / ITA וכו׳), אחרת סקטור SPDR</b> — לא בשלב 4 ועומד באחד: "שלב 2 מובהק" (פרץ התנגדות, מעל 30W SMA עולה) או "סוף שלב 1 – התעוררות" (חזר מעל 30W SMA והממוצע הפסיק לרדת — שטוח או מתעגל מעלה); כשיש ענף, הסקטור מוצג כמידע בלבד. RS — מידע בלבד; RS המניה &gt; 0 ועולה. כמות = $${f(maxRisk, 0)} ÷ (כניסה − SL).</li>
   <li>התראת טלגרם בשבת אחרי הסגירה השבועית — רק כשיש מועמדות. אין פקודות אוטומטיות.</li></ul>
  <h4>Sell-Stop (מועמדי שורט — תמונת ראי)</h4><ul>
   <li><b>כניסה = Sell-Stop</b> מתחת לתמיכת הבסיס/פסגה: רצפה − ${R.sell_stop_buf_pct ?? 0.5}% (מינימום $${R.sell_stop_min_buf ?? 0.05}). שני מצבים: (א) לפני שבירה — פסגת שלב 3 או בסיס המשך בשלב 4 (≥${R.min_base_w} ש׳), קרוב לרצפה (עד ${R.pre_bo_pct}% מעל התמיכה) ומתחת ל-30W SMA שאינו עולה; (ב) שבירה טרייה (4A) ב-${(R.bo_max_weeks_ago ?? 3) + 1} השבועות האחרונים מתחת לתמיכת ${R.base_window_w} שבועות ומתחת ל-30W SMA שטוח/יורד. מחזור בשבירה רצוי אך לא חובה בשורט (לפי ויינשטיין).</li>
   <li><b>לא רודפים:</b> עד ${R.sell_zone_pct ?? 10}% מתחת לרמת השבירה ועד ${R.max_pct_below_ma ?? 25}% מתחת ל-30W SMA.</li>
   <li><b>סטופ מגן (Buy-Stop):</b> מעל הגבוה מבין 30W SMA ושיא הפסגה האחרון שלא נשבר (+${R.stop_margin_pct}% או מעל מספר עגול עד ${R.stop_margin_max_pct}%). אם השיא גבוה מ-SMA, הסטופ &gt; ${R.max_stop_pct}% והממוצע כבר יורד — מעל השיא היורד האחרון (בין הממוצע לשיא).</li>
   <li><b>יעד ותמיכה:</b> שפל סווינג משמעותי קרוב מטה (${R.sig_pivot_w} נרות מכל צד, שנתיים); אין = שמיים פתוחים מטה (${R.min_rr}×סיכון אם מעל $0), ו־0 &lt; יעד &lt; כניסה &lt; SL, יחס R:R ≥ ${R.min_rr}.</li>
   <li><b>שערי שוק, סקטור ונתונים:</b> SPY בשלב 3 או 4 מאפשר שורטים (שלב 1, שלב 2 ו־2-weak חוסמים כי 30W SMA עדיין עולה); ענף/סקטור בשלב 3 או 4 (לעולם לא שלב 2); Mansfield RS &lt; 0 ויורד; הימנעות משורט סקוויז (שורט פלואט &lt; ${R.short_float_max_pct ?? 10}% כשידוע); סינון מקדים זהה + הוצאת קרנות כספיות/אג״ח קצר (ATR(W) &lt; ${R.cash_etf_atr_pct_max ?? 1}%).</li>
  </ul>
  <h4>סינון מקדים</h4><ul><li>מחיר ≥ $${R.min_price} · מוסדיים ${R.inst_lo}%–${R.inst_hi}% · לא ביוטק מתחת ל-$${R.biotech_cap_b}B · <b>לפחות 3 שנות היסטוריה (≥ ${R.min_weeks} נרות שבועיים)</b> — מניה צעירה יותר לא מסווגת בכלל ולא מופיעה באף לשון · <b>מחזור יומי ממוצע ≥ $${R.min_dollar_vol_m}M</b> (ממוצע ${R.dollar_vol_days} ימים של מחיר×כמות; בלי נתונים יומיים: מחזור שבועי/5 בממוצע ${R.dollar_vol_weeks} שבועות) — מניה דלילה לא מסווגת ולא מופיעה. מדדים ותעודות סקטור פטורים.</li></ul>
  <h4>עריכה</h4><p>בגרף הגדול שני קווים מלאים: אדום = תמיכה (עוגן B: שפל הבסיס האחרון שלא נשבר, אחרת 30W SMA), כחול = התנגדות (תקרת הבסיס = Buy-Stop), ופס העסקה (היעד בתוכו). גרירת הקו הכחול מזיזה את ה-Buy-Stop, גרירת האדום מזיזה את עוגן B (ה-SL מתחת לנמוך מבין הקו והממוצע). זה נשמר כ"שלך" (טבלה נפרדת — לא נוגע בשרטוטי ה-Retest או בהתראות שלו), גובר על החישוב, ו-R:R / SL% / כמות מחושבים מחדש.</p></div>`;
}

/** Mini weekly chart: candles + 30W SMA (orange) + ceiling (blue dashed) + Buy-Stop (white) + SL (red) + target (green). */
export function drawStChart(cv: HTMLCanvasElement, sp: StSpark | undefined, r?: StageRow, e?: EffPlan | null, ceil?: number | null) {
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!sp || !W || !H) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d')!; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const b = atob(sp.q), k = (sp.hi - sp.lo) / 255, n = sp.n;
  const v = (i: number) => sp.lo + b.charCodeAt(i) * k;
  const mq = atob(sp.ma), mk = (sp.hi - sp.lo) / 254;
  const lines: [number, string][] = [];
  const lvl = ceil ?? (r && isShortSide(r) ? (r.bd?.level ?? r.short_base?.floor) : (r?.bo?.level ?? r?.base?.top)); if (lvl) lines.push([lvl, '#5b8cff']);
  if (e?.stop) lines.push([e.stop, '#ef5350']);
  if (e?.target) lines.push([e.target, '#26a69a']);
  let lo = sp.lo, hi = sp.hi; lines.forEach(([p]) => { lo = Math.min(lo, p); hi = Math.max(hi, p); });
  const pad = (hi - lo) * 0.04; lo -= pad; hi += pad;
  const step = (W - 2) / n, bw = Math.max(1, step * 0.7), Y = (p: number) => 3 + (1 - (p - lo) / ((hi - lo) || 1)) * (H - 6);
  for (let i = 0; i < n; i++) {
    const o = v(i * 4), h = v(i * 4 + 1), l = v(i * 4 + 2), c = v(i * 4 + 3);
    g.fillStyle = c >= o ? '#26a69a' : '#ef5350';
    const x = 1 + i * step, cx = x + bw / 2;
    g.fillRect(cx - 0.4, Y(h), 0.8, Math.max(0.8, Y(l) - Y(h)));
    g.fillRect(x, Math.min(Y(o), Y(c)), bw, Math.max(0.8, Math.abs(Y(c) - Y(o))));
  }
  g.strokeStyle = '#ff9800'; g.lineWidth = 1.6; g.beginPath(); let pen = false;
  for (let i = 0; i < n; i++) { const q = mq.charCodeAt(i); if (q === 255 || Number.isNaN(q)) { pen = false; continue; } const x = 1 + i * step + bw / 2, y = Y(sp.lo + q * mk); pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; }
  g.stroke();
  g.setLineDash([4, 3]); g.lineWidth = 1;
  lines.forEach(([p, col]) => { g.strokeStyle = col; g.beginPath(); g.moveTo(0, Y(p)); g.lineTo(W, Y(p)); g.stroke(); });
  g.setLineDash([]);
  cv.dataset.drawn = '1';
}


/** Sector / market ETF page (#/stages/XLU, Eyal 2026-11-14): big weekly chart + 30W SMA, stage, slope and the sector
 *  rule (not stage 4 + 'שלב 2 מובהק' / 'סוף שלב 1 – התעוררות'), base ceiling when relevant. Read-only. */
export function etfCeil(e: EtfStage): number | null {
  if (e.idx) return e.stage === 2 ? null : e.range?.ceil ?? null;
  if (e.bo && e.sub === '2A') return e.bo.level;
  if (e.base) return e.base.top;
  if ((e.stage === 1 || e.stage === 3) && e.range?.ceil != null) return e.range.ceil;
  return null;
}
/** support line of an index / sector: the last confirmed swing low (stage 2) or the range floor (1 / 3 / 4) */
export function etfFloor(e: EtfStage): number | null {
  if (e.idx) return e.stage === 2 ? e.idx.support : e.range?.floor ?? null;
  return null;
}
export function etfDetailHtml(d: StagesDoc, t: string, e: EtfStage, from: string | null): string {
  const isMkt = !!d.market[t];
  const ok = isMkt && t === 'SPY' ? d.market_gate?.ok ?? e.sec_ok : e.sec_ok, cls = ok ? 'pos' : 'neg', ceil = etfCeil(e), floor = etfFloor(e);
  const users = d.rows.filter((r) => r.etf === t || r.sec_etf === t).length, x = e.idx;
  const ruleTxt = isMkt
    ? (t === 'SPY' ? `כלל השוק: ${esc(d.market_gate?.he ?? '')}` : `${esc(t)} — מידע בלבד (השער הוא SPY): ${esc(x?.td_he ?? '')}`)
    : `כלל הסקטור: ${esc(e.sec_he || (ok ? '' : 'נכשל'))}`;
  const sw = (v?: number[], ws?: string[]) => (v?.length ? v.map((p, i) => `$${f(p)}${ws?.[i] ? ` (${ddmm(ws[i])})` : ''}`).join(' → ') : '—');
  return `<div class="cv stcv stetf">
  <header class="top ch" id="chhead">
    <a id="stback" class="ghost icon btnlike" href="${from ? '#/stages/' + encodeURIComponent(from) : '#/stages'}" aria-label="חזרה">→</a>
    <div class="tk"><b dir="ltr">${esc(t)}</b> <span class="muted small" dir="ltr">$${f(e.close)}</span> ${stageBadge(e.stage, e.sub)}
      <div class="small muted stname">${esc(e.name)} · ${isMkt ? 'מדד שוק' : 'תעודת סל ענפית'}${users ? ` · ${users} מניות ברשימה` : ''}${from ? ` · חזרה ל-<bdi dir="ltr">${esc(from)}</bdi>` : ''}</div></div>
    <span></span>
  </header>
  <div class="sttags pad"><span class="badge ${isMkt && t !== 'SPY' ? 'b-off' : ok ? 'b-pass' : 'b-fail'}" id="secrule">${isMkt && t !== 'SPY' ? 'ℹ' : ok ? '✓' : '✗'} ${ruleTxt}</span>${e.td_he ? ` <span class="badge b-off" id="sectd">${esc(isMkt ? 'משמעות' : 'Top-Down')}: ${esc(e.td_he)}</span>` : ''}</div>
  <div id="stbig" class="chartwrap" dir="ltr"><div id="stnodata" class="nodata" hidden>אין נרות שבועיים</div></div>
  <div class="tools"><span class="small muted">כתום = 30W SMA${ceil != null ? ' · כחול = התנגדות (תקרת הטווח)' : ''}${floor != null ? ' · אדום = תמיכה (' + (e.stage === 2 ? 'השפל העולה האחרון' : 'רצפת הטווח') + ')' : ''} · קריאה בלבד</span></div>
  <div class="panel stpanel">
    <div class="stplan"><b>${isMkt ? 'שלב המדד (ויינשטיין, 4 פרמטרים)' : 'כלל הסקטור (ויינשטיין): לא בשלב 4, ואחד מהשניים — "שלב 2 מובהק" (פרץ התנגדות, מעל 30W SMA עולה) או "סוף שלב 1 – התעוררות" (חזר מעל 30W SMA והממוצע הפסיק לרדת)'}</b>
      <div class="skvs" id="idxkv">
        ${kv('תוצאה', isMkt && t !== 'SPY' ? 'מידע בלבד' : `${ok ? '✓ עובר' : '✗ נכשל'} · ${esc(isMkt ? `שלב ${e.stage}` : e.sec_he ?? '')}`, isMkt && t !== 'SPY' ? '' : cls)}${kv('שלב', esc(STAGE_HE[e.stage] || String(e.stage)) + (e.sub && SUB_HE[e.sub] && e.sub !== String(e.stage) ? ' · ' + esc(SUB_HE[e.sub]) : ''))}
        ${kv('1 · מחיר מול 30W SMA', x ? `${esc(POS_HE[x.pos])} (${x.above_n}/${x.of_w} מעל · ${sg(e.pct_ma)}%)` : (e.close > e.ma30 ? `מעל (${sg(e.pct_ma)}%)` : `מתחת (${sg(e.pct_ma)}%)`), e.close > e.ma30 ? 'pos' : 'neg')}${kv('2 · שיפוע הממוצע', `${SLOPE_HE(e.slope_cls)} (${sg(e.slope)}%)`, e.slope_cls === 'down' ? 'neg' : e.slope_cls === 'up' ? 'pos' : '')}
        ${kv('3 · מבנה (HH/HL)', x ? esc(x.struct === 'HH/HL' ? 'HH/HL — שיאים ושפלים עולים' : x.struct === 'LH/LL' ? 'LH/LL — שיאים ושפלים יורדים' : 'מעורב / דשדוש') : '—', x?.struct === 'HH/HL' ? 'pos' : x?.struct === 'LH/LL' ? 'neg' : '')}${kv('4 · משמעות', esc(e.td_he ?? x?.td_he ?? '—'), TD_CLS[e.td ?? ''] ?? '')}
        ${kv('שיאי סווינג', sw(x?.swing_hi, x?.swing_hi_w))}${kv('שפלי סווינג', sw(x?.swing_lo, x?.swing_lo_w))}
        ${kv('תמיכה', floor != null ? '$' + f(floor) + (x?.broke_support ? ' (נשברה)' : '') : '—', x?.broke_support ? 'neg' : '')}${kv('התנגדות', ceil != null ? '$' + f(ceil) : x?.resistance != null ? '$' + f(x.resistance) : '—')}
        ${kv('30W SMA', '$' + f(e.ma30))}${kv('Mansfield RS (מידע בלבד)', `${sg(e.rs)} ${e.rs_up == null ? '' : e.rs_up ? '↑' : '↓'}`)}
      </div></div>
    <h4>זיהוי ${esc(STAGE_HE[e.stage] || '')} (${e.score}/4)</h4><ul class="cks">${e.checks.map(chk).join('')}</ul>
    ${e.range ? `<p class="small muted">בשלב ${e.stage} מאז ${ddmm(e.range.since)} (${e.range.since_w} ש׳)${e.stage === 2 ? ' — סגירה בודדת מתחת לממוצע עולה לא מעבירה לשלב 4 כל עוד השפל העולה מחזיק (כלל 1)' : ''}.</p>` : ''}
    <p class="small muted">שבוע ${ddmm(e.week)} · <a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent((ETF_NASDAQ.has(t) ? 'NASDAQ:' : 'AMEX:') + t)}&interval=W" target="_blank" rel="noopener">TradingView</a></p>
  </div></div>`;
}
