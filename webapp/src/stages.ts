// Weinstein stage analysis page (#/stages, 'שלבים', Eyal 2026-11-13). Data: stages.json + stages_spark.json from
// srs_app/stages.py (own FinViz screen + weekly history; separate from the retest scanner). Every stock gets a stage
// 1-4 + sub-stage + the module-3 identification checks of its stage (✓ / ✗) so Eyal can verify the classification;
// 2A = new stage-2 breakout. Rules come from his masterclass page; the thresholds are printed on the page.

export interface Check { k: string; ok: boolean | null; he: string }
export interface Plan {
  kind: 'breakout' | 'trigger' | 'continuation'; entry: number; stop: number; stop_basis: 'low' | 'ma'; swing_low: number | null; target: number | null;
  target_src: 'overhead' | 'open_sky' | null; risk_pct: number | null; stop_wide: boolean; rr: number | null; shares: number | null;
  overhead: number | null; overhead_pct: number | null; open_sky: boolean; ath: boolean; cong: number | null; hi2y: number | null;
  level: number; close_vs_level: number | null; entry_vs_ma: number | null; chase: boolean; vol_need?: number | null;
}
export interface StageRow {
  t: string; n: string; ex: string; sec: string; ind: string; etf: string | null; etf_stage: number | null; etf_rs: number | null;
  mcap_b: number | null; inst: number | null; dv_m: number | null; earn: string | null; earn_td: number | null;
  stage: 1 | 2 | 3 | 4; sub: string; score: number; conf: 'high' | 'med' | 'low'; checks: Check[]; week: string;
  close: number; ma30: number; slope: number; slope_cls: string; pct_ma: number; rs: number | null; rs_prev: number | null; rs_up: boolean | null;
  hh: boolean | null; hl: boolean | null; prior: string; flat_w: number; crosses13: number; hi52: number; pct_hi52: number; at_hi52: boolean; weeks: number;
  bo: null | { week: string; weeks_ago: number; level: number; base_weeks: number; base_low: number; vol_ratio: number | null; close_pos: number | null; holding: boolean; vol_ok: boolean; pct_above: number | null; in_range?: boolean; res_week?: string };
  base?: { top: number; low: number; weeks: number; dist_pct: number; since_top_w?: number; top_week?: string | null; mature?: boolean };
  range?: { ceil: number | null; floor: number | null; since_w: number; since: string | null };
  plan?: Plan; pre: Check[]; pre_ok: boolean; entry: Check[]; entry_ok: boolean; bs?: boolean;
  earn_eff?: string | null; earn_timing?: 'a' | 'b' | null; earn_live_week?: boolean;
}
export interface EtfStage { name: string; stage: number; sub: string; score: number; conf: string; close: number; ma30: number; slope: number; pct_ma: number; rs: number | null; rs_up: boolean | null; week: string; checks: Check[] }
export interface StagesDoc {
  version: number; generated_at: string; week: string; rules: Record<string, number>; screens: Record<string, string>;
  finviz_totals: Record<string, { total: number; read: number }>; skipped: Record<string, number>;
  pre_he: Record<string, string>; buy_stop_candidates?: unknown[]; market: Record<string, EtfStage>; sectors: Record<string, EtfStage>; strong_sectors: string[]; counts: Record<string, number>; rows: StageRow[];
}
export interface StSpark { w0: string; lo: number; hi: number; n: number; q: string; ma: string }

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const f = (x: unknown, d = 2) => (x == null || x === '' || Number.isNaN(+x!) ? '—' : (+x!).toFixed(d));
const sg = (x: number | null | undefined, d = 1) => (x == null ? '—' : (x > 0 ? '+' : '') + x.toFixed(d));
const ddmm = (iso?: string | null) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '—');

export const STAGE_HE: Record<number, string> = { 1: 'שלב 1 · בסיס', 2: 'שלב 2 · עלייה', 3: 'שלב 3 · פסגה', 4: 'שלב 4 · ירידה' };
export const SUB_HE: Record<string, string> = {
  '2A': 'פריצה חדשה (2A)', '2': 'מגמה עולה', '2-ext': 'מתוחה מעל הממוצע (>35%)', '2-weak': 'מתחת לממוצע עולה (אזהרה)',
  '1A': 'בסיס מוקדם (<10 ש׳)', '1B': 'בסיס בוגר (≥10 ש׳)', '3': 'פסגה / הפצה', '4': 'מגמת ירידה', '4-late': 'מעל ממוצע יורד (אולי תחילת שלב 1)',
};
const CONF_HE: Record<string, string> = { high: 'ודאות גבוהה', med: 'ודאות בינונית', low: 'ודאות נמוכה' };
export type Tab = 'bs' | '2A' | '1' | '2' | '3' | '4' | 'novol';
export const TABS: [Tab, string][] = [['bs', 'מועמדות ל-Buy-Stop'], ['2A', 'פריצה לשלב 2 (חדשה)'], ['1', 'שלב 1'], ['2', 'שלב 2'], ['3', 'שלב 3'], ['4', 'שלב 4'], ['novol', 'פריצה בלי מחזור']];
export const SORTS: [string, string][] = [['rs', 'RS מנספילד'], ['rr', 'R:R'], ['sl_asc', 'SL% נמוך → גבוה'], ['sl_desc', 'SL% גבוה → נמוך'], ['vol', 'מחזור פריצה'], ['pct_ma', '% מהממוצע'], ['slope', 'שיפוע'], ['score', 'ודאות'], ['near', 'קרבה לפריצה'], ['t', 'סימול']];

export interface UiState { tab: Tab; q: string; sort: string; pre: boolean; ready: boolean; conf: 'all' | 'med' | 'high'; near: boolean; rulesOpen?: boolean; lastT?: string }
export const UI_DEF: UiState = { tab: 'bs', q: '', sort: 'rs', pre: false, ready: false, conf: 'all', near: false };

/** His edits on the stages page (public.stage_drawings): kind 'zone' = base ceiling / floor, 'long' = the trade bar. */
export interface StDraw { id: string; ticker: string; kind: 'zone' | 'long'; zone_top: number | null; zone_bottom: number | null; entry: number | null; stop: number | null; target: number | null; t_start: string | null; t_end: string | null; source: 'user'; status: 'active' | 'deleted'; meta?: Record<string, any> | null; updated_at?: string; created_at?: string }
export type StEdits = Map<string, { zone?: StDraw; long?: StDraw }>;

/** Trade levels in force: his trade bar when he drew / moved one, else the computed plan. R:R / SL% / shares recomputed. */
export interface EffPlan { entry: number; stop: number; target: number | null; rr: number | null; slPct: number | null; shares: number | null; wide: boolean; his: boolean; basis: string }
export function effPlan(r: StageRow, ed: { zone?: StDraw; long?: StDraw } | undefined, maxRisk: number, maxStopPct = 10): EffPlan | null {
  const p = r.plan, L = ed?.long;
  const entry = L?.entry ?? p?.entry, stop = L?.stop ?? p?.stop, target = L ? L.target : p?.target ?? null;
  if (entry == null || stop == null) return null;
  const risk = +entry - +stop;
  const rr = target != null && risk > 0 && +target > +entry ? (+target - +entry) / risk : null;
  const slPct = entry ? (risk / +entry) * 100 : null;
  return { entry: +entry, stop: +stop, target: target == null ? null : +target, rr, slPct, shares: risk > 0 ? Math.floor(maxRisk / risk) : null,
    wide: slPct != null && slPct > maxStopPct, his: !!L, basis: L ? 'שלך' : p?.stop_basis === 'low' ? 'שפל' : 'ממוצע' };
}
/** Computed base ceiling / floor shown as the editable zone: the broken base (2A), the current base, else the stage range. */
export function zoneOf(r: StageRow): { top: number; bottom: number; start: string | null } | null {
  if (r.bo && r.sub === '2A') return { top: r.bo.level, bottom: r.bo.base_low, start: r.bo.res_week ?? null };
  if (r.base) return { top: r.base.top, bottom: r.base.low, start: r.base.top_week ?? r.range?.since ?? null };
  if (r.range?.ceil != null && r.range.floor != null) return { top: r.range.ceil, bottom: r.range.floor, start: r.range.since };
  return null;
}

export function inTab(r: StageRow, tab: Tab): boolean {
  if (tab === 'bs') return !!r.bs;
  if (tab === '2A') return r.sub === '2A';
  if (tab === 'novol') return !!r.bo && r.bo.holding && !r.bo.vol_ok && !r.bo.in_range;
  return String(r.stage) === tab;
}
export function filterRows(rows: StageRow[], ui: UiState, edits?: StEdits, maxRisk = 55, maxStopPct = 10): StageRow[] {
  const q = ui.q.trim().toUpperCase();
  let out = rows.filter((r) => inTab(r, ui.tab));
  if (q) out = out.filter((r) => r.t.includes(q) || (r.n || '').toUpperCase().includes(q) || (r.sec || '').toUpperCase().includes(q) || (r.ind || '').toUpperCase().includes(q) || (r.etf || '') === q);
  if (ui.pre) out = out.filter((r) => r.pre_ok);
  if (ui.ready) out = out.filter((r) => r.entry_ok);
  if (ui.conf === 'high') out = out.filter((r) => r.conf === 'high');
  if (ui.conf === 'med') out = out.filter((r) => r.conf !== 'low');
  if (ui.near) out = out.filter((r) => r.base && r.base.dist_pct <= 5);
  const ep = (r: StageRow) => effPlan(r, edits?.get(r.t), maxRisk, maxStopPct);
  const key = (r: StageRow): number | string => {
    switch (ui.sort) {
      case 'rr': return ep(r)?.rr ?? -1e9;
      case 'sl_asc': { const v = ep(r)?.slPct; return v == null || v <= 0 ? -1e9 : -v; }
      case 'sl_desc': { const v = ep(r)?.slPct; return v == null || v <= 0 ? -1e9 : v; }
      case 'vol': return r.bo?.vol_ratio ?? -1e9;
      case 'pct_ma': return r.pct_ma ?? -1e9;
      case 'slope': return r.slope ?? -1e9;
      case 'score': return r.score * 1000 + (r.rs ?? 0);
      case 'near': return -(r.base?.dist_pct ?? r.bo?.pct_above ?? 1e9);
      case 't': return r.t;
      default: return r.rs ?? -1e9;
    }
  };
  out.sort((a, b) => { const x = key(a), y = key(b); return typeof x === 'string' ? x.localeCompare(y as string) : (y as number) - (x as number); });
  return out;
}

const chk = (c: Check) => `<li class="${c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'unk'}"><span class="ci">${c.ok === true ? '✓' : c.ok === false ? '✗' : '?'}</span>${esc(c.he)}</li>`;
export const stageBadge = (s: number, sub?: string) => `<span class="badge st st${s}">${esc(STAGE_HE[s] || 'שלב ' + s)}${sub ? ' · ' + esc(SUB_HE[sub] || sub) : ''}</span>`;

export function tvUrl(r: Pick<StageRow, 't' | 'ex'>) { return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent((r.ex || '') + ':' + r.t.replace('-', '.'))}&interval=W`; }

const kv = (k: string, v: string, cls = '') => `<div class="skv ${cls}"><span>${k}</span><b dir="ltr">${v}</b></div>`;
const earnTxt = (r: StageRow) => (r.earn ? `${ddmm(r.earn)}${r.earn_timing === 'a' ? ' אחה״ס' : r.earn_timing === 'b' ? ' לפנ״פ' : ''}${r.earn_td != null ? ` (${r.earn_td} ימ״ס)` : ''}` : '—');
/** tags of a stock: Buy-Stop candidate, open sky / overhead, don't chase, SL too wide, earnings in the live week, his levels */
export function tagsHtml(r: StageRow, e: EffPlan | null, hisZone = false): string {
  const p = r.plan, t: string[] = [];
  if (r.bs) t.push('<span class="badge b-pass">מועמדת ל-Buy-Stop</span>');
  if (p?.open_sky) t.push(`<span class="badge b-sky">שמיים פתוחים${p.ath ? ' · ATH' : ''}</span>`);
  else if (p?.overhead != null) t.push(`<span class="badge b-off" title="התנגדות תקורה">תקורה $${f(p.overhead)} (+${f(p.overhead_pct, 1)}%)</span>`);
  if (p?.chase || (!p && r.stage === 2 && (r.pct_ma ?? 0) > 25)) t.push('<span class="badge b-fail">רחוקה מדי / אל תרדוף</span>');
  if (e?.wide) t.push('<span class="badge b-fail">SL רחב מדי</span>');
  if (r.earn_live_week) t.push('<span class="badge b-fail">דוח בשבוע הקרוב</span>');
  if (e?.his || hisZone) t.push('<span class="badge b-his">הרמות שלך</span>');
  if (!r.pre_ok) t.push('<span class="badge b-off">נפסלת בסינון המקדים</span>');
  return t.join('');
}

/** One stock in the side list (like the retest list): ticker + stage + tags, mini chart, R:R / SL% / shares / rules. */
export function rowHtml(r: StageRow, e: EffPlan | null, sel: boolean, hisZone = false): string {
  const n = r.entry.length, ok = r.entry.filter((c) => c.ok === true).length;
  return `<li class="row strow2${sel ? ' sel' : ''}" data-st="${esc(r.t)}">
  <div class="r1"><b class="sttk" dir="ltr">${esc(r.t)}</b> ${stageBadge(r.stage, r.sub)} <span class="badge conf-${r.conf}" title="${r.score}/4 תנאי זיהוי">${r.score}/4</span></div>
  <div class="sttags">${tagsHtml(r, e, hisZone)}</div>
  <canvas class="stchart" data-stchart="${esc(r.t)}" aria-label="גרף שבועי שנתיים + 30W SMA"></canvas>
  <div class="skvs">
    ${kv('R:R', e?.rr != null ? '1:' + f(e.rr) : '—', e?.rr != null && e.rr >= 2.5 ? 'pos' : 'neg')}${kv('SL', e?.slPct != null ? `${f(e.slPct, 1)}% · ${e.basis}` : '—', e ? (e.wide ? 'neg' : 'pos') : '')}
    ${kv('מניות ($55)', e?.shares ? String(e.shares) : '—')}${kv('תנאי כניסה', n ? `${ok}/${n}` : '—', n ? (ok === n ? 'pos' : 'neg') : '')}
    ${kv('Buy-Stop', e ? '$' + f(e.entry) : '—')}${kv('דוח', earnTxt(r), r.earn_live_week ? 'neg' : '')}
  </div>
</li>`;
}

export function listHtml(d: StagesDoc, ui: UiState, rows: StageRow[], edits: StEdits, maxRisk: number, limit: number, selT: string | null): string {
  const cnt = (t: Tab) => d.rows.filter((r) => inTab(r, t)).length;
  const ms = +(d.rules.max_stop_pct ?? 10);
  return `<header class="top"><a id="stHome" class="ghost btnlike small" href="#/">→ Retest</a><div class="title">שלבי ויינשטיין <span class="muted small">${ddmm(d.week)}</span></div>
    <div class="hbtns"><button id="strulesBtn" class="ghost small">כללים</button></div></header>
  <div class="stfilters">
    ${topDownHtml(d)}
    <div class="chips" role="tablist">${TABS.map(([t, he]) => `<button class="chip ${ui.tab === t ? 'on' : ''}" data-tab="${t}">${he} <span class="cnt">${cnt(t)}</span></button>`).join('')}</div>
    <div class="strow"><input id="stq" type="search" placeholder="חיפוש סימול / חברה / סקטור" value="${esc(ui.q)}" />
      <label class="sortlab">מיון <select id="stsort">${SORTS.map(([k, he]) => `<option value="${k}" ${ui.sort === k ? 'selected' : ''}>${he}</option>`).join('')}</select></label></div>
    <div class="chips">
      <button class="chip ${ui.pre ? 'on' : ''}" data-tg="pre">עוברות סינון מקדים</button>
      <button class="chip ${ui.ready ? 'on' : ''}" data-tg="ready">כל תנאי הכניסה</button>
      <button class="chip ${ui.conf === 'med' ? 'on' : ''}" data-conf="med">ודאות ≥3/4</button>
      <button class="chip ${ui.conf === 'high' ? 'on' : ''}" data-conf="high">ודאות 4/4</button>
      ${ui.tab === '1' ? `<button class="chip ${ui.near ? 'on' : ''}" data-tg="near">עד 5% מתקרת הבסיס</button>` : ''}
      <button class="chip" id="stcopy">העתק ל-TradingView</button>
    </div>
    <div class="small muted" id="stcount">${rows.length} מניות · עודכן ${new Date(d.generated_at).toLocaleString('he-IL', { timeZone: 'Asia/Jerusalem', dateStyle: 'short', timeStyle: 'short' })}</div>
  </div>
  <ul class="list stlist2">${rows.slice(0, limit).map((r) => rowHtml(r, effPlan(r, edits.get(r.t), maxRisk, ms), r.t === selT, !!edits.get(r.t)?.zone)).join('') || `<li class="center muted">${ui.tab === 'bs' ? 'אין השבוע מניה שעוברת את כל הכללים ל-Buy-Stop' : 'אין מניות ברשימה הזו'}</li>`}
  ${rows.length > limit ? `<li class="center"><button id="stmore" class="ghost">הצג עוד (${rows.length - limit})</button></li>` : ''}</ul>`;
}

/** Selected stock: big weekly chart (editable base ceiling / floor + trade bar) + plan + checks. */
export function detailHtml(d: StagesDoc, r: StageRow, e: EffPlan | null, ed: { zone?: StDraw; long?: StDraw } | undefined, maxRisk: number): string {
  const p = r.plan, bo = r.bo, z = ed?.zone, zc = zoneOf(r);
  const R = d.rules, minRr = +(R.min_rr ?? 2.5);
  const ceil = z?.zone_top ?? zc?.top, floor = z?.zone_bottom ?? zc?.bottom;
  const kindHe = p ? (p.kind === 'breakout' ? 'פריצה טרייה — Buy-Stop מעל רמת הפריצה (או Pullback אליה)' : p.kind === 'continuation' ? 'בסיס המשך בשלב 2 — Buy-Stop מעל התקרה' : 'בסיס שלב 1 — Buy-Stop מעל התקרה') : 'אין עסקה מחושבת (אפשר לשרטט עסקה בעצמך)';
  const entryChecks = r.entry.map((c) => {
    if (!e?.his) return c;
    if (c.k === 'rr') return { ...c, ok: e.rr != null && e.rr >= minRr, he: `R:R ≥ ${minRr} לפי הרמות שלך (1:${f(e.rr)})` };
    if (c.k === 'stop') return { ...c, ok: !e.wide, he: `SL עד ${R.max_stop_pct}% לפי הרמות שלך (${f(e.slPct, 1)}%)` };
    return c;
  });
  return `<div class="cv stcv">
  <header class="top ch" id="chhead">
    <a id="stback" class="ghost icon btnlike" href="#/stages" aria-label="חזרה">→</a>
    <div class="tk"><a class="sttk" href="${tvUrl(r)}" target="_blank" rel="noopener" dir="ltr"><b>${esc(r.t)}</b></a> <span class="muted small" dir="ltr">$${f(r.close)}</span> ${stageBadge(r.stage, r.sub)}
      <div class="small muted stname">${esc(r.n)} · ${esc(r.sec)} / ${esc(r.ind)}${r.etf ? ` · <span class="badge st${r.etf_stage ?? 0}">${esc(r.etf)} שלב ${r.etf_stage ?? '?'}</span>` : ''}</div></div>
    <button id="stprev" class="ghost icon" aria-label="הקודם">‹</button><button id="stnext" class="ghost icon" aria-label="הבא">›</button>
  </header>
  <div class="sttags pad">${tagsHtml(r, e, !!ed?.zone)}</div>
  <div id="stbig" class="chartwrap" dir="ltr"><div id="stnodata" class="nodata" hidden>אין נרות שבועיים למניה הזו</div></div>
  <div class="tools"><span class="small muted">גרור את קווי התקרה / הרצפה ואת ה-Buy-Stop / SL / יעד — נשמר כ"שלך" וגובר על החישוב</span>
    ${ed?.zone || ed?.long ? '<button id="streset" class="ghost small">חזרה לרמות המחושבות</button>' : ''}${!p && !ed?.long ? '<button id="staddlong" class="ghost small">+ עסקה</button>' : ''}</div>
  <div class="panel stpanel">
    <div class="stplan"><b>${esc(kindHe)}</b>
      <div class="skvs">
        ${kv(e?.his ? 'Buy-Stop (שלך)' : 'Buy-Stop', e ? '$' + f(e.entry) : '—')}${kv('SL' + (e ? ` (${e.basis})` : ''), e ? `$${f(e.stop)} (${f(e.slPct, 1)}%)` : '—', e ? (e.wide ? 'neg' : 'pos') : '')}
        ${kv('יעד', e?.target != null ? '$' + f(e.target) + (e.his ? '' : p?.target_src === 'open_sky' ? ' · 2.5R' : ' · תקורה') : '—')}${kv('R:R', e?.rr != null ? '1:' + f(e.rr) : '—', e?.rr != null && e.rr >= minRr ? 'pos' : 'neg')}
        ${kv(`מניות בסיכון $${f(maxRisk, 0)}`, e?.shares ? `${e.shares} ($${f(e.shares * e.entry, 0)})` : '—')}${kv('התנגדות תקורה (שנתיים)', p ? (p.open_sky ? 'אין — שמיים פתוחים' : `$${f(p.overhead)} (+${f(p.overhead_pct, 1)}%)`) : '—', p?.open_sky ? 'pos' : '')}
        ${kv(z ? 'תקרת בסיס (שלך)' : 'תקרת בסיס', ceil != null ? '$' + f(ceil) : '—')}${kv(z ? 'רצפת בסיס (שלך)' : 'רצפת בסיס', floor != null ? '$' + f(floor) : '—')}
        ${kv('מהתקרה', ceil != null ? `${sg((r.close / ceil - 1) * 100)}%` : '—')}${kv('מ-30W SMA', sg(r.pct_ma) + '%', (r.pct_ma ?? 0) > 25 ? 'neg' : '')}
        ${p?.vol_need ? kv('מחזור נדרש בשבוע הפריצה', Math.round(p.vol_need).toLocaleString('en-US')) : ''}${bo ? kv('מחזור פריצה', f(bo.vol_ratio, 1) + 'x', bo.vol_ok ? 'pos' : 'neg') : ''}
        ${kv('דוח', earnTxt(r), r.earn_live_week ? 'neg' : '')}${kv('Mansfield RS', `${sg(r.rs)} ${r.rs_up == null ? '' : r.rs_up ? '↑' : '↓'}`, (r.rs ?? 0) > 0 ? 'pos' : 'neg')}
      </div></div>
    ${entryChecks.length ? `<h4>תנאי כניסה (${entryChecks.filter((c) => c.ok === true).length}/${entryChecks.length})</h4><ul class="cks">${entryChecks.map(chk).join('')}</ul>` : ''}
    <h4>זיהוי ${esc(STAGE_HE[r.stage])} (${r.score}/4)</h4><ul class="cks">${r.checks.map(chk).join('')}</ul>
    ${r.range ? `<p class="small muted">טווח השלב: $${f(r.range.floor)}–$${f(r.range.ceil)} · בשלב מאז ${ddmm(r.range.since)} (${r.range.since_w} ש׳) — בתוך טווח בסיס, חציית הממוצע לא משנה שלב.</p>` : ''}
    <h4>סינון מקדים</h4><ul class="cks">${r.pre.map((c) => chk({ ...c, he: c.he || d.pre_he?.[c.k] || c.k })).join('')}</ul>
    <p class="small muted">שבוע ${ddmm(r.week)} · ${r.weeks} שבועות נתונים · <a href="https://finviz.com/quote.ashx?t=${encodeURIComponent(r.t)}&p=w" target="_blank" rel="noopener">FinViz</a> · <a href="${tvUrl(r)}" target="_blank" rel="noopener">TradingView</a></p>
  </div></div>`;
}

export function topDownHtml(d: StagesDoc): string {
  const m = (k: string, e?: EtfStage) => e ? `<div class="mk"><b dir="ltr">${k}</b> ${stageBadge(e.stage, e.sub)}<span class="small muted">RS <span dir="ltr">${sg(e.rs)}</span></span></div>` : '';
  const secs = Object.entries(d.sectors).sort((a, b) => (b[1].rs ?? -99) - (a[1].rs ?? -99));
  return `<section class="topdown"><div class="mkts">${['SPY', 'QQQ', 'IWM'].map((k) => m(k, d.market[k])).join('')}</div>
  <details class="secs"><summary>סקטורים · חזקים: ${d.strong_sectors.map(esc).join(', ') || 'אין סקטור בשלב 2 עם RS חיובי'}</summary>
  <div class="tbl"><table><tr><th>תעודה</th><th>סקטור</th><th>שלב</th><th>RS</th><th>שיפוע</th><th>מ-30W</th></tr>
  ${secs.map(([k, e]) => `<tr class="${d.strong_sectors.includes(k) ? 'strong' : ''}"><td dir="ltr"><b>${k}</b>${d.strong_sectors.includes(k) ? ' ★' : ''}</td><td>${esc(e.name)}</td><td>${stageBadge(e.stage, e.sub)}</td><td dir="ltr">${sg(e.rs)} ${e.rs_up == null ? '' : e.rs_up ? '↑' : '↓'}</td><td dir="ltr">${sg(e.slope)}%</td><td dir="ltr">${sg(e.pct_ma)}%</td></tr>`).join('')}
  </table></div></details></section>`;
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
  <h4>Buy-Stop (מועמדות)</h4><ul>
   <li>כניסה = Buy-Stop מעט מעל תקרת הבסיס: תקרה + ${R.buy_stop_buf_pct}% (מינימום $${R.buy_stop_min_buf}). שני מצבים: (א) לפני פריצה — בסיס בוגר (תקרה מלפני ≥${R.min_base_w} ש׳), סגירה עד ${R.pre_bo_pct}% מתחת לתקרה ומעל 30W SMA; (ב) פריצה טרייה (2A) שעדיין באזור הקנייה.</li>
   <li>פריצה (2A): סגירה מעל תקרת ${R.base_window_w} השבועות (שנקבעה לפני ≥${R.min_base_w} ש׳) וגם מעל תקרת טווח שלב 1, מחזור שבוע הפריצה ≥ ${R.vol_mult}x ממוצע ${R.vol_avg_w} שבועות (עליות בתוך הבסיס במחזור רגיל — לא נפסל). לפני פריצה: תנאי על הטריגר — שבוע הפריצה חייב מחזור ≥ ${R.vol_mult}x.</li>
   <li><b>לא רודפים:</b> עד ${R.buy_zone_pct}% מעל רמת הפריצה ועד ${R.max_pct_above_ma}% מעל 30W SMA (מחיר או Buy-Stop), אחרת "רחוקה מדי / אל תרדוף".</li>
   <li><b>SL:</b> ${R.stop_buffer_pct}% מתחת לשפל הסווינג התקף האחרון (שפל שבועי ב-26 ש׳ שמעולם לא נשבר, מתחת לכניסה); אם אין — ${R.stop_buffer_pct}% מתחת ל-30W SMA. SL מעל ${R.max_stop_pct}% = "SL רחב מדי" (מעט מניות).</li>
   <li><b>התנגדות תקורה:</b> שיאי סווינג משמעותיים (${R.sig_pivot_w} נרות מכל צד) ב-${R.overhead_w} השבועות האחרונים מעל הכניסה (+${R.target_min_gap_pct}%). הקרובה = היעד. אין = "שמיים פתוחים": יעד = כניסה + ${R.min_rr}×סיכון (R:R ${R.min_rr} בדיוק). R:R ≥ ${R.min_rr}.</li>
   <li><b>דוחות:</b> לא משאירים Buy-Stop פתוח לשבוע של דוח (השבוע שבו ההוראה חיה; דוח אחרי הסגירה נספר ליום המסחר הבא), ולא נכנסים ${R.earn_td} ימי מסחר לפני דוח.</li>
   <li>שוק (SPY) לא בשלב 4; סקטור בשלב 2 עם RS &gt; 0; RS המניה &gt; 0 ועולה. כמות = $${f(maxRisk, 0)} ÷ (כניסה − SL).</li>
   <li>התראת טלגרם בשבת אחרי הסגירה השבועית — רק כשיש מועמדות. אין פקודות אוטומטיות.</li></ul>
  <h4>סינון מקדים</h4><ul><li>מחיר ≥ $${R.min_price} · מחזור יומי &gt; $${R.min_dollar_vol_m}M או &gt; 500K מניות בשבוע · מוסדיים ${R.inst_lo}%–${R.inst_hi}% · לא ביוטק מתחת ל-$${R.biotech_cap_b}B · ≥ ${R.min_weeks} שבועות.</li></ul>
  <h4>עריכה</h4><p>בגרף הגדול אפשר לגרור את תקרת/רצפת הבסיס ואת פס העסקה (Buy-Stop / SL / יעד). זה נשמר כ"שלך" (טבלה נפרדת — לא נוגע בשרטוטי ה-Retest או בהתראות שלו), גובר על החישוב, ו-R:R / SL% / כמות מחושבים מחדש.</p></div>`;
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
  const lvl = ceil ?? r?.bo?.level ?? r?.base?.top; if (lvl) lines.push([lvl, '#5b8cff']);
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
