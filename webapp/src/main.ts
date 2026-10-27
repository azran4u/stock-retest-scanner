import './styles.css';
import { calcPosition, fetchQuotes, quoteLabel, totals, type Position, type Quote } from './positions';
import { makeApi, OWNER_EMAIL, type Table } from './api';
import { ChartView, LONG_W_BARS } from './chart';
import { atr, decodeSpark, loadDaily, loadIndex, loadSpark, loadTv, rr, toWeekly, type Spark } from './data';
import { botLongFromZone } from './botlong';
import { maxRiskUsd, sizeLong } from './sizing';
import { FIB_KEY, SMA_COLORS, SMA_PERIODS, fibAnchor, fibConfluence, fibPrice, smaDaily, smaWeekly, type Fib } from './indicators';
import { researchHtml, type Research } from './research';
import { tvSymbol, tvList, copyText } from './tvsym';
import { BY_ID, DEF_KINDS, FILTERS, REV_HE, REV_KINDS, activeCount, isActive, matches, type Facts, type Filters, type RevKind } from './filters';
import { renderRulesHtml } from './rules';
import { CAL_LABEL, calPageHtml, drawCalChart, progress, type CalRow } from './calibrate';
import type { Bar, Command, Drawing, FeedbackCategory, Label, Row, Watch } from './types';

const api = makeApi();
const app = document.getElementById('app')!;
const LS = 'srs-app-v1';

// ---------------- state ----------------
const S = {
  email: null as string | null,
  rows: [] as Row[],
  byT: new Map<string, Row>(),
  reportDate: null as string | null,
  watch: new Map<string, Watch>(),
  drawings: new Map<string, Drawing>(),
  labels: [] as Label[],
  commands: [] as Command[],
  ui: { q: '', f: {} as Filters, fOpen: false as boolean, sort: 'default', tf: 'W' as 'W' | 'D', niWeeks: 8 as number, researchOpen: true as boolean, ma: [] as number[], fib: false, ...JSON.parse(localStorage.getItem(LS) || '{}') },
  ticker: null as string | null,
  selected: null as string | null,
  tap: null as null | { kind: 'zone' | 'long'; pts: number[]; date: string | null },
  loaded: false,
  positions: [] as Position[],
  quotes: new Map<string, Quote>(),
  research: new Map<string, Research>(),
};
// old single-select chip (before 2026-10-26) -> the equivalent independent filter
{ const c = (S.ui as any).chip as string | undefined; delete (S.ui as any).chip; if (c && c !== 'all') applyChip(S.ui.f, c); }
function applyChip(f: Filters, c: string) {
  const m: Record<string, string> = { pass: 'st_pass', waiting: 'st_pass', review: 'st_review', obsolete: 'st_obsolete', hammer: 'hammer', position: 'position', watch: 'starred', mine: 'mine', commands: 'commands' };
  if (c === 'ni') f.unfit = { on: true, mode: 'only' }; else if (m[c]) f[m[c]] = { ...(f[m[c]] || {}), on: true };
  if (c === 'watch') f.unfit = { on: true, mode: 'all' }; // the old ★ chip listed starred tickers even when marked unfit
}
const saveUi = () => localStorage.setItem(LS, JSON.stringify(S.ui));

// ---------------- helpers ----------------
const $ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector(sel) as T | null;
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const fmt = (x: unknown, d = 2) => (x == null || x === '' || Number.isNaN(+x!) ? '—' : (+x!).toFixed(d));
const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Jerusalem' });
let toastT = 0;
function toast(msg: string, err = false) {
  const t = document.getElementById('toast')!;
  t.textContent = msg; t.hidden = false; t.className = 'toast' + (err ? ' err' : '');
  clearTimeout(toastT); toastT = window.setTimeout(() => (t.hidden = true), 2600);
}
async function guard<T>(p: Promise<T>, ok?: string): Promise<T | undefined> {
  try { const r = await p; if (ok) toast(ok); return r; } catch (e: any) { toast('שגיאה: ' + (e?.message || e), true); return undefined; }
}

const BADGES: Record<string, [string, string]> = {
  pass: ['PASS', 'b-pass'], redvol: ['שבוע אדום במחזור גבוה', 'b-wait'], invh: ['פטיש הפוך', 'b-wait'], review: ['לבדיקה', 'b-review'],
  obsolete: ['לא עדכני', 'b-obs'], hammer: ['פטיש', 'b-hammer'], position: ['פוזיציה', 'b-pos'], off_screen: ['מחוץ לסריקה', 'b-off'],
  watch: ['מעקב', 'b-watch'], ni: ['לא מתאימה לשיטה', 'b-ni'], nodata: ['אין נתונים עדיין', 'b-off'],
};
/** Last-week warnings (Eyal 2026-10-23 / 2026-10-24; WAIT status cancelled 2026-10-26 -> information only, not a PASS gate):
 *  last completed weekly candle = healthy red bar on above-average volume, or an inverted hammer (BFH). */
const ddmm = (iso: unknown) => (typeof iso === 'string' && iso.length >= 10 ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '');
function waitShort(r: Row): string {
  const parts: string[] = [];
  if (r.f_no_inv_hammer === false) parts.push(`פטיש הפוך ${ddmm(r.inv_hammer_week_date)}`);
  if (r.f_no_red_vol_week === false) parts.push(`נר אדום ${ddmm(r.red_vol_week_date)} · מחזור ${fmt(r.red_vol_ratio, 2)}× ממוצע 30 יום`);
  return parts.join(' · ');
}
function waitLong(r: Row): string {
  const parts: string[] = [];
  if (r.f_no_inv_hammer === false) parts.push(`הנר השבועי של השבוע שהסתיים ב-${ddmm(r.inv_hammer_week_date)} הוא פטיש הפוך — הקונים נדחו למעלה, סימן שלילי. מידע בלבד, לא משנה את ה-PASS.`);
  if (r.f_no_red_vol_week === false) parts.push(`נר שבועי אדום בריא בשבוע שהסתיים ב-${ddmm(r.red_vol_week_date)} (גוף ${fmt(r.red_vol_body_pct, 0)}% מהטווח), עם מחזור יומי ממוצע פי ${fmt(r.red_vol_ratio, 2)} מממוצע 30 ימי המסחר שלפניו — מוכרים חזקים. מידע בלבד, לא משנה את ה-PASS.`);
  return parts.join(' ');
}
const badgeHtml = (b: string) => (BADGES[b] ? `<span class="badge ${BADGES[b][1]}">${BADGES[b][0]}</span>`
  : b.startsWith('rrfail:') ? `<span class="badge b-obs" dir="rtl">FAIL · ${esc(b.slice(7))}</span>` : '');

// ---------------- live PASS (Eyal 2026-10-23: re-check R:R whenever a drawing changes) ----------------
// PASS = exported gates ($vol, no earnings <= 14d, 3y history) AND from above AND the R:R of the ticker's
// CURRENT Long in the app >= 2. The Long that counts = newest active / approved long row (same pick as
// srs_app/app_drawings.build_store, which the nightly export uses). No Long -> R:R unknown -> not PASS.
const RR_MIN = 2;
const GATES = ['f_dollar_vol', 'f_no_earnings_14d', 'f_history'] as const;
const stamp = (d: Drawing) => String(d.updated_at || d.created_at || '');
function countedOf(t: string, kind: 'zone' | 'long'): Drawing | null {
  let best: Drawing | null = null;
  for (const d of S.drawings.values()) {
    if (d.ticker !== t || d.kind !== kind || (d.status !== 'active' && d.status !== 'approved')) continue;
    if (!best || stamp(d) > stamp(best)) best = d;
  }
  return best;
}
interface Live { status: 'PASS' | 'FAIL'; rr: number | null; gatesOk: boolean; why: string; fromBelow: boolean }
/** Mirror of report_filters.zone_approach: trailing closes under the zone = pullback in progress (skipped); then the
 * most recent weekly close outside [zb - tol, zt] decides (tol = 0.25 weekly ATR). */
function zoneApproach(closes: number[], zb: number, zt: number, tol: number): 'above' | 'below' | 'inside' {
  const lo = Math.min(zb, zt), hi = Math.max(zb, zt);
  let k = closes.length;
  while (k > 0 && closes[k - 1] < lo) k--;
  for (let i = k - 1; i >= 0; i--) {
    if (closes[i] > hi) return 'above';
    if (closes[i] < lo - tol) return 'below';
  }
  return 'inside';
}
const FROM_ABOVE_TOL_ATR = 0.25;
/** f_from_above live (Eyal 2026-10-24, USB): re-checked against the zone that counts now; no zone / closes -> export. */
function fromBelowOf(r: Row): boolean {
  const z = countedOf(r.ticker, 'zone');
  const cl = r.wk_closes;
  if (z && z.zone_top != null && z.zone_bottom != null && cl && cl.length) return zoneApproach(cl, +z.zone_bottom, +z.zone_top, FROM_ABOVE_TOL_ATR * (Number(r.weekly_atr) || 0)) === 'below';
  return r.f_from_above === false;
}
function liveOf(r: Row): Live | null {
  if (GATES.some((g) => r[g] === undefined)) return null; // no gate data exported for this row -> keep the export
  const gatesOk = GATES.every((g) => r[g] === true);
  const lg = countedOf(r.ticker, 'long');
  const q = lg ? rr(lg.entry, lg.stop, lg.target) : null;
  const rrOk = q != null && q >= RR_MIN;
  const fromBelow = fromBelowOf(r);
  const status = !gatesOk || !rrOk || fromBelow ? 'FAIL' : 'PASS'; // WAIT cancelled 2026-10-26 (red-volume / inverted-hammer weeks = info)
  const why = fromBelow ? 'חזרה לאזור מלמטה'
    : rrOk ? '' : q == null ? (lg ? 'R:R לא תקין' : 'אין לונג') : `R:R ${q.toFixed(2)} < ${RR_MIN}`;
  return { status, rr: q, gatesOk, why, fromBelow };
}
const liveRR = (r: Row) => { const l = liveOf(r); return l ? l.rr : (r.tv_rr ?? null); };
/** Levels of the Long that counts for the row (same pick as liveOf; rows without exported gates fall back to the export). */
function longLevels(r: Row): { entry: number | null; stop: number | null; target: number | null } | null {
  const lg = countedOf(r.ticker, 'long');
  if (lg) return { entry: lg.entry, stop: lg.stop, target: lg.target };
  if (liveOf(r)) return null;
  const n = (x: unknown) => (x == null || x === '' ? null : +x);
  return r.tv_entry != null ? { entry: n(r.tv_entry), stop: n(r.tv_sl), target: n(r.tv_tp) } : null;
}
/** List card line (Eyal 2026-10-24): R:R + shares / $ risk / $ reward at up to maxRisk per position (sizing.ts). */
const usd = (x: number) => '$' + (Math.abs(x) >= 100 ? Math.round(x).toLocaleString('en-US') : x.toFixed(x % 1 ? 2 : 0));
function sizingHtml(r: Row): string {
  const L = longLevels(r), mr = maxRiskUsd();
  const z = L ? sizeLong(L.entry, L.stop, L.target, mr) : null;
  const q = liveRR(r);
  const rrS = `<span class="sz-rr" dir="ltr">R:R ${q == null ? "—" : q.toFixed(2)}</span>`;
  if (!z) return `<div class="r5 small" data-sizing="none">${rrS}<span class="muted">${L ? 'לונג לא תקין' : 'אין לונג'}</span></div>`;
  if (!z.shares) return `<div class="r5 small" data-sizing="wide" data-shares="0">${rrS}<span class="sz-wide">סטופ רחב מ-<bdi dir="ltr">${usd(mr)}</bdi> למניה (<bdi dir="ltr">${usd(z.perShare)}</bdi>)</span></div>`;
  return `<div class="r5 small" data-sizing="ok" data-shares="${z.shares}" data-risk="${z.risk}" data-reward="${z.reward}">${rrS}`
    + `<span><bdi dir="ltr">${z.shares}</bdi> מניות</span>`
    + `<span>סיכון <b class="sz-risk"><bdi dir="ltr">${usd(z.risk)}</bdi></b></span>`
    + `<span>רווח <b class="sz-rew"><bdi dir="ltr">${usd(z.reward)}</bdi></b></span></div>`;
}
const secHtml = (r: Row) => {
  const sec = r.sector as string | null | undefined, ind = r.industry as string | null | undefined;
  return `<div class="r4 small muted" data-sector="${esc(sec || '')}"><span>תחום:</span> <bdi dir="ltr">${sec || ind ? esc([sec || '—', ind || '—'].join(' · ')) : '—'}</bdi></div>`;
};

function userDrawings(t: string) { return [...S.drawings.values()].filter((d) => d.ticker === t && d.status !== 'obsolete' && d.status !== 'deleted'); }
function isNi(t: string): boolean {
  const l = latestLabel(t, 'not_interesting');
  return !!l && l.value === 'yes' && (!l.until || l.until >= today());
}
const isWatched = (t: string) => S.watch.has(t);
function allRows(): Row[] {
  const out = [...S.rows];
  for (const t of S.watch.keys()) if (!S.byT.has(t)) out.push({ ticker: t, status: 'WATCH', badges: ['nodata'], has_candles: false });
  return out;
}
function badgesOf(r: Row): string[] {
  const live = liveOf(r);
  // 'waiting' (WAIT) and 'needs_drawing' are gone (Eyal 2026-10-26): never shown even from an older export
  const b = (live ? r.badges.filter((x) => x !== 'pass') : [...r.badges]).filter((x) => x !== 'waiting' && x !== 'needs_drawing');
  if (live?.status === 'PASS') b.unshift('pass');
  else if (live && live.gatesOk && live.why) b.unshift('rrfail:' + live.why); // would pass except the R:R

  if (r.f_no_inv_hammer === false) b.push('invh');
  if (r.f_no_red_vol_week === false) b.push('redvol');
  if (isWatched(r.ticker)) b.unshift('watch');
  if (isNi(r.ticker)) b.unshift('ni');
  return b;
}
const normT = (q: string) => q.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '');
async function toggleWatch(t: string) {
  if (isWatched(t)) { S.watch.delete(t); refreshViews(); await guard(api.removeWatch(t), 'הוסר מהמעקב'); }
  else { S.watch.set(t, { ticker: t, note: null }); refreshViews(); await guard(api.addWatch(t), 'נוסף למעקב ★'); }
}
/** 'לא מתאימה לשיטה' (Eyal 2026-10-24: merges 'לא מעניינת' + 'לא טכנית'). Stored as the existing label
 *  `not_interesting` (value yes, until = return date) so the nightly exclusions keep working; note = 'unfit' or
 *  'unfit: <reason>' marks the merged kind (sync.unfit_marks reads it as a "doesn't fit / not technical" verdict too). */
const UNFIT_WEEKS = [4, 8, 12, 26];
const addDays = (iso: string, n: number) => { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
async function setNi(t: string, weeks: number | null, on: boolean, untilDate?: string | null, reason?: string) {
  const until = on ? (untilDate || addDays(today(), 7 * (weeks || 8))) : null;
  const note = on ? (reason?.trim() ? `unfit: ${reason.trim()}` : 'unfit') : null;
  const l: Label = { ticker: t, label: 'not_interesting', value: on ? 'yes' : 'no', note, asof: today(), until, created_at: new Date().toISOString() };
  S.labels = S.labels.filter((x) => !(x.ticker === t && x.label === l.label && x.asof === l.asof)); S.labels.push(l);
  unfitOpen = false;
  refreshViews();
  await guard(api.upsertLabel(l), on ? `לא מתאימה לשיטה · חוזרת ב-${ddmm(until)}` : 'חזרה לרשימה');
}
let unfitOpen = false;
/** status line + undo when marked; else duration picks (default 8 weeks) + custom date + optional reason */
function unfitHtml(t: string): string {
  const l = latestLabel(t, 'not_interesting');
  if (isNi(t)) {
    const days = l?.until ? Math.round((Date.parse(l.until) - Date.parse(today())) / 864e5) : null;
    const why = l?.note && l.note.startsWith('unfit: ') ? l.note.slice(7) : '';
    return `<div class="unfit on"><span class="badge b-ni" id="unfitState">לא מתאימה לשיטה${l?.until ? ` · חוזרת ב-${ddmm(l.until)}${days != null ? ` (עוד ${days} ימים)` : ''}` : ' · ללא תאריך חזרה'}</span>
      ${why ? `<span class="muted small">${esc(why)}</span>` : ''}<button id="niOff" class="ok small">החזר עכשיו</button></div>`;
  }
  const w = UNFIT_WEEKS.includes(S.ui.niWeeks) ? S.ui.niWeeks : 8;
  return `<div class="unfit"><div class="row2 wk">${UNFIT_WEEKS.map((n) => `<button class="wkb ${n === w ? 'on' : ''}" data-w="${n}">${n} ש׳</button>`).join('')}
      <label class="small muted">או עד <input id="unfitDate" type="date" dir="ltr" min="${addDays(today(), 1)}"/></label></div>
    <div class="row2"><input id="unfitWhy" class="grow" placeholder="סיבה (לא חובה)"/><button id="niOn" class="bad">לא מתאימה לשיטה</button></div>
    <div class="muted small" id="unfitWhen">תחזור לרשימה ב-${ddmm(addDays(today(), 7 * w))}</div></div>`;
}
function bindUnfit(root: ParentNode, t: string) {
  const sel = () => +(($('.wkb.on', root) as HTMLElement | null)?.dataset.w || 8);
  const when = () => { const d = ($('#unfitDate', root) as HTMLInputElement | null)?.value; const e = $('#unfitWhen', root); if (e) e.textContent = `תחזור לרשימה ב-${ddmm(d || addDays(today(), 7 * sel()))}`; };
  root.querySelectorAll<HTMLButtonElement>('.wkb').forEach((b) => (b.onclick = () => {
    root.querySelectorAll('.wkb').forEach((x) => x.classList.toggle('on', x === b));
    const di = $('#unfitDate', root) as HTMLInputElement | null; if (di) di.value = '';
    S.ui.niWeeks = +b.dataset.w!; saveUi(); when();
  }));
  const di = $('#unfitDate', root) as HTMLInputElement | null; if (di) di.onchange = when;
  const on = $('#niOn', root); if (on) on.onclick = () => setNi(t, sel(), true, di?.value || null, ($('#unfitWhy', root) as HTMLInputElement | null)?.value);
  const off = $('#niOff', root); if (off) off.onclick = () => setNi(t, null, false);
}
function refreshViews() {
  if (cv && S.ticker) { renderHeader(); syncChart(); renderPanel(); }
  else if ($('.list')) updateListBody();
}
function latestLabel(t: string, label: string): Label | undefined {
  let best: Label | undefined;
  for (const l of S.labels) if (l.ticker === t && l.label === label) {
    if (!best || l.asof > best.asof || (l.asof === best.asof && (l.created_at || '') > (best.created_at || ''))) best = l;
  }
  return best;
}

// ---------------- distance to the zone (Eyal 2026-10-24: sort by proximity instead of a near-zone PASS gate) ----------------
// Live zone = the zone that counts now (countedOf, same pick as the stock page); no app zone -> exported TV zone.
// dist = 0 inside [bottom, top], else |price - nearest edge| / weekly ATR (= report_filters.compute_near_zone).
interface ZoneDist { atr: number; side: 'inside' | 'above' | 'below' }
const numOrNull = (x: unknown) => (x == null || x === '' || !Number.isFinite(+x) ? null : +x);
/** Zone that counts now for a ticker: newest active / approved app zone, else the exported TV zone. */
function liveZoneOf(t: string, r?: Row): { top: number; bottom: number } | null {
  const z = countedOf(t, 'zone');
  const top = z ? numOrNull(z.zone_top) : numOrNull(r?.tv_zone_top), bot = z ? numOrNull(z.zone_bottom) : numOrNull(r?.tv_zone_bottom);
  return top == null || bot == null ? null : { top: Math.max(top, bot), bottom: Math.min(top, bot) };
}
function zoneDistOf(r: Row): ZoneDist | null {
  const z = countedOf(r.ticker, 'zone');
  const n = numOrNull;
  let top = z ? n(z.zone_top) : n(r.tv_zone_top), bot = z ? n(z.zone_bottom) : n(r.tv_zone_bottom);
  const px = n(r.current_price), a = n(r.weekly_atr);
  if (top == null || bot == null || px == null) return null;
  if (bot > top) [top, bot] = [bot, top];
  const side = px > top ? 'above' : px < bot ? 'below' : 'inside';
  const d = side === 'inside' ? 0 : side === 'above' ? px - top : bot - px;
  if (!a || a <= 0) return !z && r.tv_zone_dist_atr != null ? { atr: +r.tv_zone_dist_atr, side } : null;
  return { atr: d / a, side };
}
function zoneDistHtml(r: Row): string {
  const z = zoneDistOf(r);
  if (!z) return `<div class="r6 small muted" data-zdist="">מרחק מהאזור: אין אזור</div>`;
  const where = z.side === 'inside' ? ' (בתוך האזור)' : z.side === 'below' ? ' (מתחת לאזור)' : '';
  return `<div class="r6 small" data-zdist="${z.atr.toFixed(4)}">מרחק מהאזור: <b dir="ltr">${z.atr.toFixed(1)} ATR</b>${where}</div>`;
}

// ---------------- Fibonacci confluence (Eyal 2026-10-24; informational, NOT a PASS gate) ----------------
// Anchor = last confirmed weekly swing low -> highest high after it (indicators.ts = srs_app/fib.py, RULES.md §Fib).
// Price near a key level: within 0.25 weekly ATR; zone coincides: key level inside the live zone ± 0.1 weekly ATR.
function fibText(f: { low: number; high: number }, atrW: number | null | undefined, price: number | null | undefined, z: { top: number; bottom: number } | null): string {
  const c = fibConfluence(f, atrW, price, z?.top, z?.bottom);
  const parts: string[] = [];
  if (c.priceLevel != null) parts.push(`המחיר ליד פיבו <b dir="ltr">${c.priceLevel}</b>`);
  if (c.zoneLevels.length) parts.push(`האזור מתלכד עם פיבו <b dir="ltr">${c.zoneLevels.join(' / ')}</b>`);
  return parts.join(' · ');
}
function rowFib(r: Row): { low: number; high: number } | null {
  const m = fibManual(r.ticker); if (m) return m; // his own anchors win everywhere
  const lo = numOrNull(r.fib_low), hi = numOrNull(r.fib_high);
  return lo == null || hi == null ? null : { low: lo, high: hi };
}
function fibRowHtml(r: Row): string {
  const f = rowFib(r); if (!f) return '';
  const txt = fibText(f, numOrNull(r.fib_atr) ?? numOrNull(r.weekly_atr), numOrNull(r.current_price), liveZoneOf(r.ticker, r));
  return txt ? `<div class="r7 small fibline">פיבונאצי${fibManual(r.ticker) ? ' (ידני)' : ''}: ${txt}</div>` : '';
}

function filtered(): Row[] {
  const q = S.ui.q.trim().toUpperCase();
  let rows = allRows().filter((r) => {
    if (q && !r.ticker.includes(q)) return false;
    return matches(factsOf(r), S.ui.f); // independent filters, logical AND (filters.ts)
  });
  const num = (x: unknown) => (x == null ? -Infinity : +x);
  const s = S.ui.sort;
  if (s === 'ticker') rows = [...rows].sort((a, b) => a.ticker.localeCompare(b.ticker));
  else if (s === 'rr') rows = [...rows].sort((a, b) => num(liveRR(b)) - num(liveRR(a)));
  else if (s === 'zone') {
    const zd = new Map(rows.map((r) => [r.ticker, zoneDistOf(r)?.atr ?? Infinity]));
    const pz = new Map(rows.map((r) => [r.ticker, badgesOf(r).includes('pass') ? 0 : 1]));
    rows = [...rows].sort((a, b) => zd.get(a.ticker)! - zd.get(b.ticker)! || pz.get(a.ticker)! - pz.get(b.ticker)! || a.ticker.localeCompare(b.ticker)); // no zone -> last; ties: PASS first
  }
  else if (s === 'hammer') {
    // only gated hammers (badge from export_data.hammer_ok) rank by hammer score
    const hs = (r: Row) => num(r.badges.includes('hammer') ? r.hammer_score : null);
    rows = [...rows].sort((a, b) => hs(b) - hs(a) || a.ticker.localeCompare(b.ticker));
  }
  else {
    const rank = (r: Row) => { const bs = badgesOf(r); return bs.includes('position') ? 0 : isWatched(r.ticker) ? 0.5 : bs.includes('pass') ? 1 : bs.includes('review') ? 2 : r.badges.includes('hammer') ? 3 : 5; };
    const rk = new Map(rows.map((r) => [r.ticker, [rank(r), num(liveRR(r))] as const]));
    rows = [...rows].sort((a, b) => rk.get(a.ticker)![0] - rk.get(b.ticker)![0] || rk.get(b.ticker)![1] - rk.get(a.ticker)![1] || a.ticker.localeCompare(b.ticker));
  }
  return rows;
}

/** Days to the next earnings, live from earnings_date (Israel today); null = no date. Eyal 2026-10-26:
 *  earnings_none = no date in TradingView / Yahoo / Nasdaq (ETFs...) -> 'אין דוחות', passes the 14-day gate;
 *  earnings_estimated = last report + 91 days (no next date published yet). */
function daysToEarn(r: Row): number | null {
  const ed = typeof r.earnings_date === 'string' ? r.earnings_date.slice(0, 10) : null;
  return ed ? daysBetween(today(), ed) : null;
}
function earnShort(r: Row): string {
  if (r.earnings_none) return '';
  const d = daysToEarn(r);
  return d == null ? '' : r.earnings_estimated ? `earn ~${d}d (est.)` : `earn ${d}d`;
}
// ---------------- per-row facts for the filters (export values + live app values) ----------------
const daysBetween = (a: string, b: string) => Math.round((Date.parse(b + 'T00:00:00Z') - Date.parse(a + 'T00:00:00Z')) / 864e5);
const bool = (x: unknown) => (x === true ? true : x === false ? false : null);
function factsOf(r: Row): Facts {
  const bs = badgesOf(r), live = liveOf(r), td = today();
  const ed = typeof r.earnings_date === 'string' ? r.earnings_date.slice(0, 10) : null;
  const zd = zoneDistOf(r);
  const f = rowFib(r);
  const fc = f ? fibConfluence(f, numOrNull(r.fib_atr) ?? numOrNull(r.weekly_atr), numOrNull(r.current_price), liveZoneOf(r.ticker, r)?.top, liveZoneOf(r.ticker, r)?.bottom) : null;
  const wa = numOrNull(r.weekly_atr);
  return {
    technical: bool(r.f_technical),
    rr: liveRR(r),
    revD: (r.rev_d as Facts['revD']) || {}, revW: (r.rev_w as Facts['revW']) || {},
    daysToEarn: ed ? daysBetween(td, ed) : null, earnNone: r.earnings_none === true,
    unfit: isNi(r.ticker),
    status: live ? live.status : bs.includes('pass') ? 'PASS' : String(r.status || ''),
    needsDrawing: bs.includes('needs_drawing'), review: bs.includes('review'), obsolete: bs.includes('obsolete'), hammer: bs.includes('hammer'),
    position: bs.includes('position') || S.positions.some((p) => p.ticker === r.ticker),
    starred: isWatched(r.ticker), mine: userDrawings(r.ticker).length > 0, commands: S.commands.some((x) => x.ticker === r.ticker),
    zoneDist: zd ? zd.atr : null,
    dollarVol: numOrNull(r.dollar_vol_30d),
    history: bool(r.f_history),
    tradable: wa == null ? null : wa < maxRiskUsd(),
    fromAbove: live ? !live.fromBelow : bool(r.f_from_above),
    noInvHammer: bool(r.f_no_inv_hammer), noRedVol: bool(r.f_no_red_vol_week),
    smoothWeeks: numOrNull(r.smooth_streak_weeks),
    sector: (r.sector as string) || null,
    instOwn: numOrNull(r.inst_own_pct), shortFloat: numOrNull(r.short_float_pct),
    fib: !!fc && (fc.priceLevel != null || fc.zoneLevels.length > 0),
    today: td,
  };
}

// ---------------- filter panel (Eyal 2026-10-26: each filter on its own, several = AND) ----------------
function fpanelHtml(): string {
  const fs = S.ui.f, sectors = [...new Set(S.rows.map((r) => r.sector).filter(Boolean) as string[])].sort();
  const item = (id: string) => {
    const d = BY_ID.get(id)!, st = fs[id] || { on: false };
    if (d.tri) {
      const m = st.mode || 'hide';
      return `<div class="fi fi-tri" data-f="${id}"><span class="fl">${d.label}:</span>${(['hide', 'only', 'all'] as const).map((k) => `<button class="seg ${m === k ? 'on' : ''}" data-mode="${k}">${{ hide: 'הסתר', only: 'רק הן', all: 'הצג גם' }[k]}</button>`).join('')}</div>`;
    }
    let extra = '';
    if (d.param) { const x = st.x ?? d.param.def; extra += `<input class="fx" type="number" inputmode="decimal" dir="ltr" min="${d.param.min}" max="${d.param.max}" step="${d.param.step}" value="${x}" aria-label="${esc(d.label)}" />${d.param.unit ? `<span class="fu muted">${d.param.unit}</span>` : ''}`; }
    if (d.select === 'sector') extra += `<select class="fsel" aria-label="תחום"><option value="">בחר…</option>${sectors.map((x) => `<option ${st.v === x ? 'selected' : ''} value="${esc(x)}">${esc(x)}</option>`).join('')}</select>`;
    let kinds = '';
    if (d.kinds) { const ks = st.kinds?.length ? st.kinds : DEF_KINDS; kinds = `<div class="fk">${REV_KINDS.map((k) => `<button class="kd ${ks.includes(k) ? 'on' : ''}" data-k="${k}">${REV_HE[k]}</button>`).join('')}</div>`; }
    return `<div class="fi ${isActive(id, st) ? 'act' : ''}" data-f="${id}"><label class="ft"><input type="checkbox" ${st.on ? 'checked' : ''} /><span class="fl">${d.label}</span></label>${extra}${kinds}</div>`;
  };
  const grp = (g: string, title: string) => `<div class="fg"><div class="fgt">${title}</div>${FILTERS.filter((d) => d.group === g).map((d) => item(d.id)).join('')}</div>`;
  return grp('main', 'עיקריים') + grp('status', 'סטטוס ואפליקציה') + grp('setup', 'סטאפ ונתונים');
}
function bindFpanel() {
  const fs = S.ui.f, p = $('#fpanel'); if (!p) return;
  const upd = () => { saveUi(); updateListBody(); updateFHead(); };
  p.querySelectorAll<HTMLElement>('.fi').forEach((el) => {
    const id = el.dataset.f!, d = BY_ID.get(id)!;
    const st = () => (fs[id] ||= { on: false });
    el.querySelectorAll<HTMLButtonElement>('.seg').forEach((b) => (b.onclick = () => { st().mode = b.dataset.mode as any; st().on = true; el.querySelectorAll('.seg').forEach((x) => x.classList.toggle('on', x === b)); upd(); }));
    const cb = el.querySelector<HTMLInputElement>('input[type=checkbox]');
    if (cb) cb.onchange = () => { st().on = cb.checked; el.classList.toggle('act', isActive(id, st())); upd(); };
    const nx = el.querySelector<HTMLInputElement>('.fx');
    if (nx) nx.oninput = () => { const v = parseFloat(nx.value); if (!Number.isFinite(v)) return; st().x = v; st().on = true; if (cb) cb.checked = true; el.classList.add('act'); upd(); };
    const sel = el.querySelector<HTMLSelectElement>('.fsel');
    if (sel) sel.onchange = () => { st().v = sel.value; st().on = !!sel.value; if (cb) cb.checked = st().on; el.classList.toggle('act', isActive(id, st())); upd(); };
    el.querySelectorAll<HTMLButtonElement>('.kd').forEach((b) => (b.onclick = () => {
      const cur = new Set<RevKind>(st().kinds?.length ? st().kinds : DEF_KINDS), k = b.dataset.k as RevKind;
      if (cur.has(k)) { if (cur.size > 1) cur.delete(k); } else cur.add(k);
      st().kinds = REV_KINDS.filter((x) => cur.has(x)); st().on = true; if (cb) cb.checked = true; el.classList.add('act');
      el.querySelectorAll<HTMLElement>('.kd').forEach((x) => x.classList.toggle('on', cur.has(x.dataset.k as RevKind))); upd();
    }));
    void d;
  });
}
function updateFHead() {
  const n = activeCount(S.ui.f), b = $('#ftog'); if (b) b.innerHTML = `סינון${n ? ` <span class="fcount">${n}</span>` : ''} ${S.ui.fOpen ? '▴' : '▾'}`;
  const c = $('#fclear') as HTMLButtonElement | null; if (c) c.hidden = !n;
  const c2 = $('#fclear2') as HTMLButtonElement | null; if (c2) c2.hidden = !n;
}

// ---------------- copy TradingView symbol (Eyal 2026-10-27) ----------------
let copyBox: HTMLElement | null = null;
async function doCopy(text: string, okMsg?: string) {
  if (!text) return;
  if (await copyText(text)) { toast(okMsg || `הועתק: ${text}`); return; }
  // clipboard blocked: show the text selected so a long-press / Ctrl+C copies it
  copyBox?.remove();
  copyBox = document.createElement('div'); copyBox.className = 'sheet copybox';
  copyBox.innerHTML = `<div class="sh-head"><b>העתק ידנית</b><button class="ghost small" aria-label="סגור">✕</button></div><textarea readonly dir="ltr" rows="3"></textarea>`;
  document.body.appendChild(copyBox);
  const ta = copyBox.querySelector('textarea')!; ta.value = text; ta.focus(); ta.select();
  copyBox.querySelector('button')!.onclick = () => { copyBox?.remove(); copyBox = null; };
}

// ---------------- routing ----------------
function route() {
  syncBotFab();
  if (!S.email) return renderLogin();
  if (S.email.toLowerCase() !== OWNER_EMAIL) return renderDenied();
  if (!S.loaded) { app.innerHTML = '<div class="center muted">טוען…</div>'; return; }
  const m = location.hash.match(/^#\/t\/([^/?]+)/);
  if (m) openTicker(decodeURIComponent(m[1]).toUpperCase());
  else if (location.hash.startsWith('#/rules')) renderRules();
  else if (location.hash.startsWith('#/calibrate')) renderCalibrate();
  else renderList();
}
window.addEventListener('hashchange', route);

// ---------------- login ----------------
function renderLogin() {
  destroyChart();
  app.innerHTML = `
  <div class="login">
    <div class="logo">📈</div>
    <h1>Retest Scanner</h1>
    <p class="muted">כניסה עם קישור או קוד שנשלח במייל</p>
    <input id="em" type="email" inputmode="email" autocomplete="email" dir="ltr" value="${esc(localStorage.getItem('srs-email') || OWNER_EMAIL)}" />
    <button id="send" class="primary big">שלח קישור התחברות</button>
    <div id="codebox" class="codebox" hidden>
      <p class="muted">נשלח מייל. פתח את הקישור, או (באפליקציה שבמסך הבית) הקלד כאן את הקוד מהמייל:</p>
      <input id="code" inputmode="numeric" autocomplete="one-time-code" dir="ltr" maxlength="10" placeholder="123456" />
      <button id="verify" class="primary big">אמת קוד</button>
    </div>
  </div>`;
  $('#send')!.onclick = async () => {
    const em = ($('#em') as HTMLInputElement).value.trim();
    localStorage.setItem('srs-email', em);
    const ok = await guard(api.sendLink(em).then(() => true), 'נשלח');
    if (ok) $('#codebox')!.hidden = false;
  };
  $('#verify')!.onclick = async () => {
    const em = ($('#em') as HTMLInputElement).value.trim();
    await guard(api.verifyCode(em, ($('#code') as HTMLInputElement).value));
  };
}
function renderDenied() {
  app.innerHTML = `<div class="login"><h1>אין הרשאה</h1><p class="muted" dir="ltr">${esc(S.email)}</p><button id="out" class="big">התנתק</button></div>`;
  $('#out')!.onclick = () => api.signOut();
}

// ---------------- list ----------------
function renderList() {
  destroyChart();
  const rows = filtered();
  app.innerHTML = `
  <header class="top">
    <div class="title">Retest <span class="muted small">${esc(S.reportDate || '')}</span></div>
    <div class="hbtns"><a id="calLink" class="ghost small btnlike" href="#/calibrate">כיול מגמה</a><a id="rulesLink" class="ghost small btnlike" href="#/rules">כללים</a><button id="logout" class="ghost small">יציאה</button></div>
  </header>
  <div class="filters">
    <input id="q" type="search" dir="ltr" placeholder="חיפוש טיקר" value="${esc(S.ui.q)}" autocapitalize="characters" />
    <div class="fhead"><button id="ftog" class="chip ${S.ui.fOpen ? 'on' : ''}" aria-expanded="${!!S.ui.fOpen}"></button><button id="fclear" class="ghost small" hidden>ניקוי הכל</button></div>
    <div id="fpanel" class="fpanel" ${S.ui.fOpen ? '' : 'hidden'}>
      <div class="fsh-head"><b>סינון</b><button id="fclear2" class="ghost small">ניקוי הכל</button><button id="fdone" class="primary small">הצג <span id="fdn">${rows.length}</span> מניות</button></div>
      <div id="fbody" class="fbody">${fpanelHtml()}</div>
    </div>
    <div class="sortrow"><span class="muted small">${rows.length} מניות</span><button id="copyList" class="ghost small cpyall" title="העתק את הרשימה המסוננת כסימולים של TradingView">📋 העתק ל-TV</button>
      <label class="sortlab"><span>מיון:</span><select id="sort" aria-label="מיון">
        ${[['default', 'עדיפות'], ['zone', 'קרבה לאזור'], ['rr', 'R:R'], ['hammer', 'ציון פטיש'], ['ticker', 'א-ב']].map(([v, t]) => `<option value="${v}" ${S.ui.sort === v ? 'selected' : ''}>${t}</option>`).join('')}
      </select></label></div>
  </div>
  <ul class="list">${listInner(rows)}</ul>`;
  const q = $('#q') as HTMLInputElement;
  q.oninput = () => { S.ui.q = q.value; saveUi(); updateListBody(); };
  const setFOpen = (o: boolean) => { S.ui.fOpen = o; saveUi(); $('#fpanel')!.hidden = !o; $('#ftog')!.classList.toggle('on', o); document.body.classList.toggle('fsheet-open', o); updateFHead(); };
  $('#ftog')!.onclick = () => setFOpen(!S.ui.fOpen);
  $('#fdone')!.onclick = () => setFOpen(false);
  const clearF = () => { S.ui.f = {}; saveUi(); $('#fbody')!.innerHTML = fpanelHtml(); bindFpanel(); updateListBody(); updateFHead(); };
  $('#fclear')!.onclick = clearF; $('#fclear2')!.onclick = clearF;
  document.body.classList.toggle('fsheet-open', !!S.ui.fOpen);
  bindFpanel(); updateFHead();
  ($('#sort') as HTMLSelectElement).onchange = (e) => { S.ui.sort = (e.target as HTMLSelectElement).value; saveUi(); renderList(); };
  $('#logout')!.onclick = () => api.signOut();
  $('#copyList')!.onclick = () => { const rs = filtered(); if (rs.length) doCopy(tvList(rs), `הועתקו ${rs.length} סימולים ל-TradingView`); };
  bindRows();
  const y = sessionStorage.getItem('srs-scroll'); if (y) window.scrollTo(0, +y);
}
// ---------------- rules page (#/rules) ----------------
let rulesP: Promise<any> | null = null;
async function renderRules() {
  destroyChart();
  app.innerHTML = `<header class="top"><button id="back" class="ghost">→ רשימה</button><div class="title">כללים</div><span></span></header><div class="rules center muted">טוען…</div>`;
  $('#back')!.onclick = () => { location.hash = '#/'; };
  rulesP ??= fetch(import.meta.env.BASE_URL + 'data/rules.json', { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const j = await rulesP;
  if (!location.hash.startsWith('#/rules')) return;
  const el = $('.rules')!; el.className = 'rules';
  el.innerHTML = `<p class="small"><a href="#/calibrate">כיול מגמה →</a> (סימון 60 מניות לכיול כלל המגמה)</p>` + renderRulesHtml(j, { maxRisk: maxRiskUsd() });
}
// ---------------- trend calibration page (#/calibrate, calibrate.ts) ----------------
let calP: Promise<CalRow[]> | null = null;
let calIO: IntersectionObserver | null = null;
async function renderCalibrate() {
  destroyChart();
  app.innerHTML = `<header class="top"><button id="back" class="ghost">→ רשימה</button><div class="title">כיול מגמה</div><span></span></header><div class="cal center muted">טוען…</div>`;
  $('#back')!.onclick = () => { location.hash = '#/'; };
  calP ??= fetch(import.meta.env.BASE_URL + 'data/calibration.json', { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : [])).catch(() => []);
  const [rows, sp] = await Promise.all([calP, loadSpark()]);
  if (!location.hash.startsWith('#/calibrate')) return;
  const el = $('.cal')!; el.className = 'cal';
  if (!rows.length) { el.innerHTML = '<p class="center muted">אין נתוני כיול</p>'; return; }
  el.innerHTML = calPageHtml(rows, S.labels);
  calIO?.disconnect();
  calIO = new IntersectionObserver((ents) => ents.forEach((e) => {
    if (e.isIntersecting) { const c = e.target as HTMLCanvasElement; drawCalChart(c, (sp as any)[c.dataset.calchart!]); calIO?.unobserve(c); }
  }), { rootMargin: '400px 0px' });
  el.querySelectorAll<HTMLCanvasElement>('canvas.calchart').forEach((c) => calIO!.observe(c));
  el.querySelectorAll<HTMLElement>('.calcard').forEach((card) => {
    const t = card.dataset.cal!;
    card.querySelectorAll<HTMLButtonElement>('[data-mark]').forEach((b) => (b.onclick = async () => {
      const note = (card.querySelector('.calnote') as HTMLInputElement).value.trim() || null;
      const l: Label = { ticker: t, label: CAL_LABEL, value: b.dataset.mark!, note, asof: today(), until: null, created_at: new Date().toISOString() };
      S.labels = S.labels.filter((x) => !(x.ticker === t && x.label === l.label && x.asof === l.asof)); S.labels.push(l);
      card.querySelectorAll<HTMLButtonElement>('[data-mark]').forEach((x) => x.classList.toggle('on', x === b));
      const p = progress(rows, S.labels); $('#calprog')!.textContent = `סומנו ${p.done}/${p.total}`;
      let mk = card.querySelector('.calmarked'); if (!mk) { mk = document.createElement('span'); mk.className = 'badge b-pass calmarked'; card.querySelector('.r1')!.appendChild(mk); }
      mk.textContent = 'סומן: ' + b.textContent;
      await guard(api.upsertLabel(l), `${t}: ${b.textContent}`);
    }));
    // a note typed after the mark re-saves the current mark with it
    (card.querySelector('.calnote') as HTMLInputElement).onchange = () => (card.querySelector<HTMLButtonElement>('[data-mark].on'))?.click();
  });
}
function updateListBody() {
  const rows = filtered();
  $('.list')!.innerHTML = listInner(rows);
  $('.sortrow .small')!.textContent = `${rows.length} מניות`;
  const fdn = $('#fdn'); if (fdn) fdn.textContent = String(rows.length);
  bindRows();
}
function listInner(rows: Row[]) {
  const q = normT(S.ui.q);
  const add = q && !allRows().some((r) => r.ticker === q)
    ? `<li class="addrow"><button class="primary" id="addWatch" data-t="${esc(q)}">★ הוסף ${esc(q)} למעקב</button><div class="muted small">לא ברשימת המועמדים. נרות יתווספו בריצה הלילית.</div></li>` : '';
  return add + (rows.map(rowHtml).join('') || (add ? '' : '<li class="muted center">אין תוצאות</li>'));
}
// ---------------- list mini charts (3y weekly closes, drawn lazily when a row scrolls into view) ----------------
let sparks: Record<string, Spark> | null = null;
let sparkIO: IntersectionObserver | null = null;
function drawSpark(cv: HTMLCanvasElement) {
  if (!sparks) return;
  const t = cv.dataset.spark!, sp = sparks[t];
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!sp || !W || !H) { cv.classList.toggle('empty', !sp); return; }
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d')!; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  cv.dataset.drawn = '1';
  const B = decodeSpark(sp), n = B.c.length;
  // zone band + entry line of the ticker's drawings (zone / long), scale stretched to include them
  const ds = userDrawings(t).filter((d) => d.status !== 'rejected');
  const zone = ds.find((d) => d.kind === 'zone' && d.zone_top != null && d.zone_bottom != null);
  const long = ds.find((d) => d.kind === 'long' && d.entry != null);
  const lv = [B.lo, B.hi];
  if (zone) lv.push(+zone.zone_top!, +zone.zone_bottom!);
  if (long) lv.push(+long.entry!);
  let lo = Math.min(...lv), hi = Math.max(...lv);
  const pad = (hi - lo) * 0.04 || 1; lo -= pad; hi += pad;
  const top = 2, bot = H - 2, padL = 1, padR = 1;
  const step = (W - padL - padR) / n;             // ~2.3px per week at 390px
  const bw = Math.max(1, step - 0.5);              // body width, ~0.5px gap
  const Y = (p: number) => bot - ((p - lo) / (hi - lo)) * (bot - top);
  if (zone) {
    const y1 = Y(+zone.zone_top!), y2 = Y(+zone.zone_bottom!);
    g.fillStyle = zone.source === 'bot' ? 'rgba(255,152,0,.22)' : 'rgba(41,98,255,.26)';
    g.fillRect(0, Math.min(y1, y2), W, Math.max(1.5, Math.abs(y2 - y1)));
  }
  for (let i = 0; i < n; i++) {
    const up = B.c[i] >= B.o[i];
    g.fillStyle = up ? '#26a69a' : '#ef5350';
    const x = padL + i * step, cx = Math.round((x + bw / 2) * 2) / 2;
    const yh = Y(B.h[i]), yl = Y(B.l[i]);
    g.fillRect(cx - 0.25, yh, 0.5, Math.max(0.5, yl - yh));                 // wick
    const yo = Y(B.o[i]), yc = Y(B.c[i]);
    g.fillRect(x, Math.min(yo, yc), bw, Math.max(0.8, Math.abs(yc - yo)));  // body
  }
  // daily SMAs (sampled weekly, export_data.spark_ma) + Fib key levels, following the chart toggles
  const mas: number[] = S.ui.ma || [];
  if (mas.length && sp.ma) {
    const q = atob(sp.ma.q), k = (sp.ma.hi - sp.ma.lo) / 254;
    g.lineWidth = 1.2;
    SMA_PERIODS.forEach((p, s) => {
      if (!mas.includes(p)) return;
      g.strokeStyle = SMA_COLORS[p]; g.beginPath(); let pen = false;
      for (let i = 0; i < n; i++) {
        const c = q.charCodeAt(i * 4 + s); if (c === 255 || Number.isNaN(c)) { pen = false; continue; }
        const x = padL + i * step + bw / 2, y = Y(sp.ma!.lo + c * k);
        if (pen) g.lineTo(x, y); else { g.moveTo(x, y); pen = true; }
      }
      g.stroke();
    });
  }
  const rf = S.ui.fib && S.byT.get(t) ? rowFib(S.byT.get(t)!) : null;
  if (rf) {
    g.setLineDash([2, 2]); g.lineWidth = 1;
    for (const [x, col] of [[0.382, '#4dd0e1'], [0.5, '#ffca28'], [0.618, '#ff7043']] as const) {
      const y = Y(fibPrice(rf, x)); g.strokeStyle = col; g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke();
    }
    g.setLineDash([]);
  }
  if (long) {
    const y = Y(+long.entry!); g.setLineDash([4, 3]); g.strokeStyle = 'rgba(209,212,220,.8)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); g.setLineDash([]);
  }
  // min / max labels (3y weekly range)
  const f = (x: number) => (x >= 100 ? x.toFixed(0) : x.toFixed(2));
  g.direction = 'ltr'; g.textAlign = 'left'; g.font = '9px -apple-system, Arial, sans-serif';
  g.fillStyle = 'rgba(19,23,34,.7)'; g.fillRect(1, 1, f(B.hi).length * 5.4 + 4, 11); g.fillRect(1, H - 12, f(B.lo).length * 5.4 + 4, 11);
  g.fillStyle = 'rgba(178,181,190,.9)'; g.textBaseline = 'top'; g.fillText(f(B.hi), 3, 2);
  g.textBaseline = 'bottom'; g.fillText(f(B.lo), 3, H - 2);
}
function observeSparks() {
  const els = app.querySelectorAll<HTMLCanvasElement>('canvas.spark');
  if (!els.length) return;
  if (!sparks) { loadSpark().then((s) => { sparks = s; observeSparks(); }); return; }
  sparkIO?.disconnect();
  sparkIO = new IntersectionObserver((ents) => ents.forEach((e) => {
    if (e.isIntersecting) { drawSpark(e.target as HTMLCanvasElement); sparkIO?.unobserve(e.target); }
  }), { rootMargin: '300px 0px' });
  els.forEach((c) => sparkIO!.observe(c));
}

// list mini charts keep their proportions when the window is resized (desktop grid): redraw the painted ones
let sparkRT = 0, sparkW = window.innerWidth;
window.addEventListener('resize', () => {
  if (window.innerWidth === sparkW) return; // iOS fires resize on toolbar show/hide (height only)
  sparkW = window.innerWidth; clearTimeout(sparkRT);
  sparkRT = window.setTimeout(() => app.querySelectorAll<HTMLCanvasElement>('canvas.spark[data-drawn]').forEach(drawSpark), 150);
});
function bindRows() {
  observeSparks();
  const aw = $('#addWatch') as HTMLButtonElement | null;
  if (aw) aw.onclick = async () => { const t = aw.dataset.t!; await toggleWatch(t); S.ui.q = ''; saveUi(); location.hash = '#/t/' + t; };
  app.querySelectorAll<HTMLButtonElement>('.row .star').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); toggleWatch(b.dataset.star!); }));
  app.querySelectorAll<HTMLButtonElement>('.row .cpy').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); doCopy(b.dataset.copy!); }));
  app.querySelectorAll<HTMLElement>('.row').forEach((li) => (li.onclick = () => {
    sessionStorage.setItem('srs-scroll', String(window.scrollY));
    location.hash = '#/t/' + li.dataset.t;
  }));
}
function rowHtml(r: Row) {
  const mine = userDrawings(r.ticker);
  const tech = latestLabel(r.ticker, 'technical');
  const pend = S.commands.filter((c) => c.ticker === r.ticker && c.status === 'pending').length;
  const extra = [
    mine.length ? `<span class="badge b-mine">✎ ${mine.length}</span>` : '',
    tech ? `<span class="badge ${tech.value === 'yes' ? 'b-pass' : 'b-obs'}">${tech.value === 'yes' ? 'טכנית' : 'לא טכנית'}</span>` : '',
    pend ? `<span class="badge b-review">⌛ ${pend}</span>` : '',
    isNi(r.ticker) && latestLabel(r.ticker, 'not_interesting')?.until ? `<span class="muted small">חוזרת ב-${ddmm(latestLabel(r.ticker, 'not_interesting')!.until)}</span>` : '',
  ].join('');
  return `<li class="row" data-t="${esc(r.ticker)}">
    <div class="r1"><span><button class="star ${isWatched(r.ticker) ? 'on' : ''}" data-star="${esc(r.ticker)}" aria-label="מעקב">${isWatched(r.ticker) ? '★' : '☆'}</button><b dir="ltr">${esc(r.ticker)}</b><button class="ghost cpy" data-copy="${esc(tvSymbol(r))}" aria-label="העתק ל-TradingView" title="${esc(tvSymbol(r))}">📋</button></span><span class="px" dir="ltr">${fmt(r.current_price)}</span></div>
    <div class="r2">${badgesOf(r).map(badgeHtml).join('')}${extra}</div>
    <canvas class="spark" data-spark="${esc(r.ticker)}" aria-hidden="true"></canvas>
    ${secHtml(r)}
    ${sizingHtml(r)}
    ${zoneDistHtml(r)}
    ${fibRowHtml(r)}
    <div class="r3 muted small" dir="ltr">${[r.badges.includes('hammer') ? `hammer R:R ${fmt(r.hammer_rr)}` : '', earnShort(r)].filter(Boolean).join(' · ')}</div>
    ${r.earnings_none ? '<div class="r3 small muted earn-none">אין דוחות</div>' : ''}
    ${r.data_dup_of ? `<div class="r3 small wait-why dupwarn">⚠ נתוני המחיר זהים ל-<bdi>${esc(r.data_dup_of)}</bdi>, ייתכן שהגרף שגוי</div>` : ''}
    ${waitShort(r) ? `<div class="r3 small wait-why">${esc(waitShort(r))}</div>` : ''}
  </li>`;
}

// ---------------- chart view ----------------
let cv: ChartView | null = null;
let curBars: { daily: Bar[]; weekly: Bar[] } | null = null;
let loadSeq = 0;
function destroyChart() { if (cv) { cv.destroy(); cv = null; } }

function navList(): string[] { return filtered().map((r) => r.ticker); }
function neighbor(dir: 1 | -1): string | null {
  const l = navList(); if (!S.ticker) return null;
  let i = l.indexOf(S.ticker);
  if (i < 0) i = dir > 0 ? -1 : l.length;
  return l[i + dir] ?? null;
}
function go(dir: 1 | -1) { const t = neighbor(dir); if (t) location.replace('#/t/' + t); else toast(dir > 0 ? 'סוף הרשימה' : 'תחילת הרשימה'); }

function shell() {
  app.innerHTML = `
  <div class="cv">
    <header class="top ch" id="chhead">
      <button id="back" class="ghost icon" aria-label="חזרה">→</button>
      <div class="tk"><b id="tk" dir="ltr"></b><button id="tkCopy" class="ghost cpy" aria-label="העתק ל-TradingView">📋</button> <span id="tkpx" class="muted small" dir="ltr"></span><div id="tkb" class="tkb"></div></div>
      <button id="star" class="ghost icon star" aria-label="מעקב">☆</button>
      <button id="niBtn" class="ghost small nib" aria-label="לא מעניינת">🚫</button>
      <button id="prev" class="ghost icon" aria-label="הקודם">‹</button>
      <button id="next" class="ghost icon" aria-label="הבא">›</button>
    </header>
    <div id="unfitPop" class="unfitpop" hidden></div>
    <div id="chart" class="chartwrap" dir="ltr"><div id="nodata" class="nodata" hidden>אין עדיין נתוני נרות למניה הזו.<br/>הם יתווספו בריצה הלילית הבאה.</div></div>
    <div class="tools" id="tools">
      <div class="seg"><button data-tf="W">שבועי</button><button data-tf="D">יומי</button></div>
      <button id="addZone">+ אזור</button>
      <button id="addLong">+ לונג</button>
    </div>
    <div class="indbar" id="indbar">${indChipsHtml()}</div>
    <nav class="jump" id="jump" aria-label="מעבר לחלק בעמוד">${JUMPS.map(([k, l]) => `<button class="chip jmp" data-jump="${k}">${l}</button>`).join('')}</nav>
    <div id="hint" class="hint" hidden></div>
    <div class="panel" id="panel"></div>
  </div>`;
  cv = new ChartView($('#chart')!, {
    onSelect: (id) => { S.selected = id; syncChart(); renderPanel(); },
    onDragMove: (d) => updateCardValues(d),
    onDragEnd: async (id, patch) => {
      const d = S.drawings.get(id);
      if (d) { Object.assign(patch, ownEdit(d)); Object.assign(d, patch, { updated_at: new Date().toISOString() }); }
      renderHeader(); renderPanel();
      await guard(api.updateDrawing(id, patch));
      if (d?.kind === 'zone') await followZone(d);
    },
    onTap: (price, date) => onChartTap(price, date),
    onFibDrop: (which, time) => onFibPick(which, time),
    onFibMove: (which, time) => {           // lines follow the handle while dragging (saved on release)
      const p = snapWick(time, which), f = fibOfCur(); if (!p || !f || !cv) return;
      const lo = which === 'low' ? { d: p.date, v: p.price } : { d: f.low_date, v: f.low };
      const hi = which === 'high' ? { d: p.date, v: p.price } : { d: f.high_date, v: f.high };
      if (hi.d <= lo.d || hi.v <= lo.v) return;
      const tm = (d: string) => (S.ui.tf === 'W' ? mondayOfIso(d) : d);
      cv.setFib({ low: lo.v, high: hi.v, lowTime: tm(lo.d), highTime: tm(hi.d) }, false);
    },
  });
  $('#back')!.onclick = () => { location.hash = '#/'; };
  $('#star')!.onclick = () => S.ticker && toggleWatch(S.ticker);
  $('#tkCopy')!.onclick = (e) => { e.stopPropagation(); doCopy(($('#tkCopy') as HTMLElement).dataset.copy || ''); };
  $('#niBtn')!.onclick = () => { if (!S.ticker) return; unfitOpen = !unfitOpen; renderUnfitPop(); };
  $('#prev')!.onclick = () => go(-1);
  $('#next')!.onclick = () => go(1);
  app.querySelectorAll<HTMLButtonElement>('[data-tf]').forEach((b) => (b.onclick = () => { S.ui.tf = b.dataset.tf as 'W' | 'D'; saveUi(); applyBars(); }));
  $('#addZone')!.onclick = () => startTap('zone');
  $('#addLong')!.onclick = () => startTap('long');
  bindIndChips();
  app.querySelectorAll<HTMLButtonElement>('[data-jump]').forEach((b) => (b.onclick = () => jumpTo(b.dataset.jump!)));
  swipe($('#chhead')!); swipe($('#panel')!); swipe($('#tools')!);
}

// ---------------- stock page section jumps (Eyal 2026-10-27, mobile: the overview / bot box were below the fold) ----------------
const JUMPS: [string, string][] = [['research', 'סקירה'], ['secDraw', 'שרטוטים'], ['secCmd', '💬 פקודה לבוט'], ['secFib', 'פיבונאצי'], ['secUnfit', 'לא מתאימה'], ['secNote', 'הערה'], ['secData', 'נתונים']];
function jumpTo(id: string) {
  const el = document.getElementById(id); if (!el) return;
  if (el instanceof HTMLDetailsElement) el.open = true;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (id === 'secCmd') setTimeout(() => ($('#cmd') as HTMLTextAreaElement | null)?.focus({ preventScroll: true }), 350);
}
function syncJumps() {
  app.querySelectorAll<HTMLButtonElement>('[data-jump]').forEach((b) => { b.hidden = !document.getElementById(b.dataset.jump!); });
}

// ---------------- indicators on the chart (Eyal 2026-10-24): daily SMA 50/100/150/200 + Fibonacci ----------------
// Toggles under the chart tools, saved in localStorage (S.ui.ma, S.ui.fib); the list mini charts follow the same toggles.
function indChipsHtml(): string {
  const ma: number[] = S.ui.ma || [];
  const all = SMA_PERIODS.every((n) => ma.includes(n));
  return SMA_PERIODS.map((n) => `<button class="chip ind ${ma.includes(n) ? 'on' : ''}" data-ma="${n}"><i style="background:${SMA_COLORS[n]}"></i><span dir="ltr">MA${n}</span></button>`).join('')
    + `<button class="chip ind ${all ? 'on' : ''}" data-ma="all">כל הממוצעים</button>`
    + `<button class="chip ind fibchip ${S.ui.fib ? 'on' : ''}" data-fib="1">פיבונאצי</button>`;
}
function bindIndChips() {
  const bar = $('#indbar'); if (!bar) return;
  bar.innerHTML = indChipsHtml();
  bar.querySelectorAll<HTMLButtonElement>('[data-ma]').forEach((b) => (b.onclick = () => {
    const ma: number[] = [...(S.ui.ma || [])], k = b.dataset.ma!;
    if (k === 'all') S.ui.ma = SMA_PERIODS.every((n) => ma.includes(n)) ? [] : [...SMA_PERIODS];
    else { const n = +k; S.ui.ma = ma.includes(n) ? ma.filter((x) => x !== n) : [...ma, n].sort((a, c) => a - c); }
    saveUi(); bindIndChips(); applyIndicators();
  }));
  const fb = bar.querySelector<HTMLButtonElement>('[data-fib]');
  if (fb) fb.onclick = () => { S.ui.fib = !S.ui.fib; saveUi(); bindIndChips(); applyIndicators(); renderPanel(); };
}
let curFib: { t: string; f: Fib | null } | null = null;
function fibAuto(): Fib | null {
  if (!curBars || !S.ticker) return null;
  if (curFib?.t !== S.ticker) curFib = { t: S.ticker, f: fibAnchor(curBars.daily) };
  return curFib.f;
}
/** Fib that counts on the stock page: a draft low being placed > his manual anchors > the automatic anchor. */
function fibOfCur(): (Fib & { manual: boolean }) | null {
  const auto = fibAuto(), t = S.ticker; if (!t) return null;
  const m = fibManual(t), atrW = auto?.atr_w ?? numOrNull(S.byT.get(t)?.fib_atr) ?? numOrNull(S.byT.get(t)?.weekly_atr);
  const base = m ? { ...m, atr_w: atrW, manual: true } : auto ? { ...auto, manual: false } : null;
  return base;
}

// ---------------- manual Fib anchors (Eyal 2026-10-24: "start at the beginning of the up-wave, end at the top; take the wick") ----------------
// Stored per ticker as label 'fib_anchor' (value = JSON {low, low_date, high, high_date, at} or 'auto' = back to automatic),
// so it syncs between his iPhone and desktop via Supabase; localStorage keeps a copy (fallback / offline). Newest wins.
type FibAnchor = { low: number; low_date: string; high: number; high_date: string; at: string };
const FIB_LS = 'srs-fib-anchors-v1';
const fibLocal = (): Record<string, FibAnchor | { auto: true; at: string }> => { try { return JSON.parse(localStorage.getItem(FIB_LS) || '{}'); } catch { return {}; } };
function fibManual(t: string): FibAnchor | null {
  const l = latestLabel(t, 'fib_anchor');
  let fromLabel: any = null;
  if (l) { if (l.value === 'auto') fromLabel = { auto: true, at: l.created_at || l.asof }; else { try { fromLabel = JSON.parse(l.value); } catch { fromLabel = null; } } }
  const loc: any = fibLocal()[t] || null;
  const pick = !fromLabel ? loc : !loc ? fromLabel : String(loc.at || '') > String(fromLabel.at || '') ? loc : fromLabel;
  if (!pick || pick.auto || pick.low == null || pick.high == null || !(+pick.high > +pick.low)) return null;
  return { low: +pick.low, low_date: String(pick.low_date), high: +pick.high, high_date: String(pick.high_date), at: String(pick.at || '') };
}
async function saveFibManual(t: string, a: Omit<FibAnchor, 'at'> | null) {
  const at = new Date().toISOString();
  const loc = fibLocal(); loc[t] = a ? { ...a, at } : { auto: true, at };
  try { localStorage.setItem(FIB_LS, JSON.stringify(loc)); } catch { /* full */ }
  const l: Label = { ticker: t, label: 'fib_anchor', value: a ? JSON.stringify({ ...a, at }) : 'auto', note: null, asof: today(), created_at: at };
  S.labels = S.labels.filter((x) => !(x.ticker === t && x.label === l.label && x.asof === l.asof)); S.labels.push(l);
  refreshFib();
  await guard(api.upsertLabel(l), a ? 'פיבונאצי ידני נשמר' : 'פיבונאצי חזר לאוטומטי');
}
/** The candle at bar time `time` of the current timeframe, snapped to its wick: low -> its low, high -> its high, with the
 *  daily date of that extreme (a weekly candle -> the day inside the week where the low / high was made). */
function snapWick(time: string, which: 'low' | 'high'): { date: string; price: number } | null {
  if (!curBars) return null;
  const days = S.ui.tf === 'W' ? curBars.daily.filter((b) => mondayOfIso(b.time) === time) : curBars.daily.filter((b) => b.time === time);
  if (!days.length) return null;
  let best = days[0];
  for (const b of days) if (which === 'low' ? b.low < best.low : b.high > best.high) best = b;
  return { date: best.time, price: which === 'low' ? best.low : best.high };
}
function refreshFib() {
  applyIndicators(); renderPanel();
}
/** A Fib end was dragged (line or dot) and dropped on the candle at bar time `barTime`; the chart already picked the
 *  candle whose wick is nearest to the drop point. Low end -> that candle's low, high end -> its high (wick), then save. */
async function onFibPick(which: 'low' | 'high', barTime: string) {
  const t = S.ticker; if (!t) return;
  const p = snapWick(barTime, which);
  if (!p) { toast('אין נר בנקודה הזו', true); refreshFib(); return; }
  const cur = fibOfCur();
  const low = which === 'low' ? p : cur ? { date: cur.low_date, price: cur.low } : null;
  const high = which === 'high' ? p : cur ? { date: cur.high_date, price: cur.high } : null;
  if (!low || !high) { refreshFib(); return; }
  if (high.date <= low.date || high.price <= low.price) { toast('השיא חייב להיות אחרי השפל וגבוה ממנו', true); refreshFib(); return; }
  await saveFibManual(t, { low: low.price, low_date: low.date, high: high.price, high_date: high.date });
}
const mondayOfIso = (d: string) => { const t = new Date(d + 'T00:00:00Z'); t.setUTCDate(t.getUTCDate() - ((t.getUTCDay() + 6) % 7)); return t.toISOString().slice(0, 10); };
function applyIndicators() {
  if (!cv || !curBars) return;
  const weekly = S.ui.tf === 'W', daily = curBars.daily;
  cv.setMAs(((S.ui.ma || []) as number[]).filter((n) => SMA_PERIODS.includes(n as any)).map((n) => ({
    n, color: SMA_COLORS[n],
    data: weekly ? smaWeekly(daily, n) : smaDaily(daily, n).map((v, i) => (v == null ? null : { time: daily[i].time, value: v })).filter((x): x is { time: string; value: number } => !!x),
  })));
  const f = S.ui.fib ? fibOfCur() : null;
  const tm = (d: string) => (weekly ? mondayOfIso(d) : d);
  cv.setFib(f ? { low: f.low, high: f.high, lowTime: tm(f.low_date), highTime: tm(f.high_date) } : null);
  // Eyal 2026-10-24: no edit button - whenever the Fib is shown its two end lines (and end dots) are grabbed directly
  cv.setFibEdit(f ? { low: { time: tm(f.low_date), price: f.low }, high: { time: tm(f.high_date), price: f.high } } : null);
}
function fibPanelHtml(r: Row | undefined): string {
  const t = S.ticker; if (!t) return '';
  const m = fibManual(t);
  const f = fibOfCur() ?? (m ? { ...m, atr_w: numOrNull(r?.fib_atr), manual: true }
    : r && rowFib(r) ? { ...rowFib(r)!, low_date: String(r.fib_low_date || ''), high_date: String(r.fib_high_date || ''), atr_w: numOrNull(r.fib_atr), manual: false } : null);
  const btns = `<div class="muted small fibhow">${S.ui.fib ? 'למיקום: גרור על הגרף את הקו העליון או התחתון של הפיבונאצי (גם מהצד, ליד המחיר) או את הנקודות. בשחרור הוא נצמד לפתיל הקרוב.' : ''}</div>${m ? '<div class="acts fibacts"><button id="fibAuto" class="ghost">אפס לאוטומטי</button></div>' : ''}`;
  if (!f) return `<section class="fibbox" id="secFib"><h3>פיבונאצי</h3><div class="muted small">אין עדיין שפל ושיא ברורים בגרף השבועי. אפשר למקם ידנית.</div>${btns}</section>`;
  const px = curBars ? curBars.daily[curBars.daily.length - 1]?.close : numOrNull(r?.current_price);
  const txt = fibText(f, f.atr_w, px, liveZoneOf(t, r));
  const lv = FIB_KEY.map((x) => `<span><b dir="ltr">${x}</b> <span dir="ltr">${fibPrice(f, x).toFixed(2)}</span></span>`).join('');
  return `<section class="fibbox" id="secFib" data-fib-low="${f.low}" data-fib-high="${f.high}" data-fib-manual="${f.manual ? 1 : 0}"><h3>פיבונאצי <span class="badge ${f.manual ? 'b-fibm' : ''}">${f.manual ? 'ידני' : 'אוטומטי'}</span></h3>
    <div class="small">מהשפל <bdi dir="ltr">${f.low.toFixed(2)}</bdi> (${ddmm(f.low_date)}/${f.low_date.slice(2, 4)}) לשיא <bdi dir="ltr">${f.high.toFixed(2)}</bdi> (${ddmm(f.high_date)}/${f.high_date.slice(2, 4)})</div>
    <div class="fiblv small">${lv}</div>
    <div class="small fibconf">${txt || '<span class="muted">המחיר והאזור לא מתלכדים עם 0.382 / 0.5 / 0.618.</span>'}</div>
    <div class="muted small">מידע בלבד, לא תנאי ל-PASS.${S.ui.fib ? '' : ' להצגה על הגרף: כפתור "פיבונאצי" מתחת לגרף.'}</div>${btns}</section>`;
}

function swipe(el: HTMLElement) {
  let x0 = 0, y0 = 0, t0 = 0;
  el.addEventListener('touchstart', (e) => { const t = e.touches[0]; x0 = t.clientX; y0 = t.clientY; t0 = Date.now(); }, { passive: true });
  el.addEventListener('touchend', (e) => {
    const t = e.changedTouches[0]; const dx = t.clientX - x0, dy = t.clientY - y0;
    if (Date.now() - t0 < 600 && Math.abs(dx) > 70 && Math.abs(dx) > 2 * Math.abs(dy)) go(dx < 0 ? 1 : -1);
  }, { passive: true });
}

async function openTicker(t: string) {
  const first = !cv;
  if (first) shell();
  if (S.ticker !== t) { S.selected = null; S.tap = null; }
  S.ticker = t;
  renderHeader(); renderHint(); renderPanel();
  ($('#nodata') as HTMLElement).hidden = true;
  const seq = ++loadSeq;
  try {
    const daily = await loadDaily(t);
    if (seq !== loadSeq) return;
    curBars = { daily, weekly: toWeekly(daily) };
    applyBars();
    renderPanel();
  } catch (e: any) {
    if (seq !== loadSeq) return;
    curBars = null; cv?.setBars([], 0); cv?.setAtr(null); ($('#nodata') as HTMLElement).hidden = false;
  }
  // prefetch neighbours for fast swipes
  for (const d of [1, -1] as const) { const n = neighbor(d); if (n) loadDaily(n).catch(() => {}); }
}

function renderUnfitPop() {
  const p = $('#unfitPop'); if (!p) return;
  p.hidden = !unfitOpen || !S.ticker;
  if (p.hidden) return;
  p.innerHTML = `<div class="row2"><b>לא מתאימה לשיטה</b><button id="unfitClose" class="ghost small" aria-label="סגור">✕</button></div>${unfitHtml(S.ticker!)}`;
  bindUnfit(p, S.ticker!);
  $('#unfitClose', p)!.onclick = () => { unfitOpen = false; renderUnfitPop(); };
}
function renderHeader() {
  const t = S.ticker; if (!t) return;
  const r = S.byT.get(t) || allRows().find((x) => x.ticker === t) || { ticker: t, status: '', badges: [] };
  $('#tk')!.textContent = t;
  const cp = $('#tkCopy')!; cp.dataset.copy = tvSymbol(r as Row); cp.title = cp.dataset.copy;
  $('#tkpx')!.textContent = r.current_price != null ? fmt(r.current_price) : '';
  $('#tkb')!.innerHTML = badgesOf(r as Row).filter((b) => b !== 'watch').map(badgeHtml).join('');
  const st = $('#star')!; st.textContent = isWatched(t) ? '★' : '☆'; st.classList.toggle('on', isWatched(t));
  $('#niBtn')!.classList.toggle('on', isNi(t));
  renderUnfitPop();
}

function applyBars() {
  app.querySelectorAll<HTMLButtonElement>('[data-tf]').forEach((b) => b.classList.toggle('on', b.dataset.tf === S.ui.tf));
  if (!cv || !curBars) return;
  const bars = S.ui.tf === 'W' ? curBars.weekly : curBars.daily;
  syncChart();
  cv.setBars(bars, S.ui.tf === 'W' ? 110 : 160, S.ui.tf === 'W');
  // weekly ATR (Wilder 14) from the weekly candles, whatever timeframe is shown; scanner value as fallback
  const wAtr = atr(curBars.weekly) ?? (S.ticker ? S.byT.get(S.ticker)?.weekly_atr ?? null : null);
  cv.setAtr(wAtr == null ? null : +wAtr);
  applyIndicators();
  cv.fitLevels();
}

function syncChart() {
  if (!cv || !S.ticker) return;
  cv.setDrawings(userDrawings(S.ticker).filter((d) => d.status !== 'rejected'), S.selected);
  cv.fitLevels();
}

function startTap(kind: 'zone' | 'long') {
  if (!curBars) return;
  S.tap = S.tap?.kind === kind ? null : { kind, pts: [], date: null };
  if (S.tap && S.selected) { S.selected = null; syncChart(); renderPanel(); } // hide handles so taps hit the chart
  renderHint();
}
function renderHint() {
  const h = $('#hint'); if (!h) return;
  const t = S.tap;
  ['addZone', 'addLong'].forEach((id) => $('#' + id)?.classList.toggle('on', !!t && (id === 'addZone') === (t.kind === 'zone')));
  if (!t) { h.hidden = true; return; }
  h.hidden = false;
  h.innerHTML = (t.kind === 'zone'
    ? (t.pts.length === 0 ? 'הקש על הגרף בגבול הראשון של האזור (גם תאריך ההתחלה)' : `גבול ראשון ${t.pts[0]} — הקש על הגבול השני`)
    : (t.pts.length === 0 ? 'הקש על מחיר הכניסה (גם תאריך ההתחלה)' : `כניסה ${t.pts[0]} — הקש על הסטופ (היעד יוצב על 2R, אפשר לגרור)`))
    + ' <button id="cancelTap" class="ghost small">ביטול</button>';
  $('#cancelTap')!.onclick = () => { S.tap = null; renderHint(); };
}

async function onChartTap(price: number, date: string) {
  const t = S.tap;
  if (!t || !S.ticker) { if (S.selected) { S.selected = null; syncChart(); renderPanel(); } return; }
  t.pts.push(price);
  if (t.pts.length === 1) { t.date = date; renderHint(); return; }
  const [a, b] = t.pts;
  let row: Partial<Drawing>;
  if (t.kind === 'zone') {
    if (a === b) { t.pts.pop(); toast('הגבולות זהים', true); return; }
    row = { ticker: S.ticker, kind: 'zone', zone_top: Math.max(a, b), zone_bottom: Math.min(a, b), t_start: t.date, source: 'user', status: 'active' };
  } else {
    if (b >= a) { t.pts.pop(); toast('הסטופ חייב להיות מתחת לכניסה', true); return; }
    // anchored in time: t_start = tapped candle, t_end = LONG_W_BARS bars later (moves with pan / zoom)
    const tEnd = t.date && cv ? cv.shiftDate(t.date, LONG_W_BARS) : null;
    row = { ticker: S.ticker, kind: 'long', entry: a, stop: b, target: Math.round((a + 2 * (a - b)) * 100) / 100, t_start: t.date, t_end: tEnd, source: 'user', status: 'active' };
  }
  S.tap = null; renderHint();
  const d = await guard(api.insertDrawing(row), 'נשמר');
  if (d) { S.drawings.set(d.id, d); S.selected = d.id; renderHeader(); syncChart(); renderPanel(); if (d.kind === 'zone') await followZone(d); }
}

// ---------------- bot drawings: edits + feedback ----------------
const LEVELS = ['zone_top', 'zone_bottom', 'entry', 'stop', 'target', 't_start', 't_end'] as const;
const levelsOf = (d: Drawing) => Object.fromEntries(LEVELS.map((k) => [k, d[k] ?? null]));
const FB: [FeedbackCategory, string, string][] = [
  // 'structure' (מבנה לא מתאים לשיטה) removed 2026-10-26 (Eyal): the 'לא מתאימה לשיטה' mark covers it
  ['zone', 'אזור לא נכון', 'bad'], ['position', 'פוזיציה לא נכונה', 'bad'], ['approved', 'מאושר', 'ok'],
];
const botSnap = new Map<string, Record<string, any>>(); // levels of a bot row before his first edit
/** First edit of a bot drawing: it becomes his (source user, counts as his drawing), the bot's levels are kept in meta.bot_before. */
function ownEdit(d: Drawing): Partial<Drawing> {
  if (d.source !== 'bot') return {};
  const before = botSnap.get(d.id) ?? levelsOf(d);
  return { source: 'user', meta: { ...(d.meta || {}), bot_before: before, edited_at: new Date().toISOString() } };
}
const isBotOrigin = (d: Drawing) => d.source === 'bot' || !!d.meta?.bot_before;
function fbCommands(d: Drawing) {
  return S.commands.filter((c) => c.kind === 'feedback' && Array.isArray(c.payload?.drawing_ids) && c.payload!.drawing_ids.includes(d.id));
}
async function sendFeedback(d: Drawing, cat: FeedbackCategory, note: string) {
  const t = d.ticker;
  const bots = userDrawings(t).filter(isBotOrigin);
  // which rows the feedback is about: structure = all of the ticker's bot rows, zone / position = that kind, approved = this row
  const target = cat === 'structure' ? bots : cat === 'zone' ? bots.filter((x) => x.kind === 'zone')
    : cat === 'position' ? bots.filter((x) => x.kind === 'long') : [d];
  const rows = target.length ? target : [d];
  const before: Record<string, any> = {}, after: Record<string, any> = {};
  let edited = false;
  for (const x of rows) {
    before[x.kind] = x.meta?.bot_before ?? levelsOf(x);
    if (x.meta?.bot_before) { after[x.kind] = levelsOf(x); edited = true; }
  }
  const label = FB.find((f) => f[0] === cat)?.[1] ?? cat;
  const payload = {
    ticker: t, drawing_ids: rows.map((x) => x.id), category: cat, category_he: label, note: note || null,
    before, after: edited ? after : null, rule_version: d.meta?.rule_version ?? null, why: d.meta?.why ?? null,
  };
  // negative feedback: stops counting toward PASS now (rejected) until the bot redraws under a fixed rule
  const status = cat === 'approved' ? 'approved' : 'rejected';
  for (const x of rows) { if (x.source === 'bot') x.status = status; }
  renderHeader(); syncChart(); renderPanel();
  for (const x of rows) if (x.source === 'bot') await guard(api.updateDrawing(x.id, { status }));
  const c = await guard(api.addCommand(t, `[feedback] ${cat}: ${note || label}`, 'feedback', payload), 'המשוב נשלח לבוט');
  if (c) {
    if (!S.commands.some((x) => x.id === c.id)) S.commands.unshift(c);
    await guard(api.addFeedback({ ticker: t, drawing_ids: payload.drawing_ids, category: cat, note: note || null, before,
      after: payload.after, rule_version: payload.rule_version, why: payload.why, command_id: c.id }));
    renderPanel();
  }
}
function feedbackHtml(d: Drawing) {
  if (!isBotOrigin(d)) return '';
  const cs = fbCommands(d);
  const hist = cs.slice(0, 3).map((c) => `<li><span class="badge ${c.status === 'done' ? 'b-pass' : c.status === 'error' ? 'b-obs' : 'b-review'}">${{ pending: 'ממתין', done: 'בוצע', error: 'שגיאה' }[c.status]}</span> ${esc(c.payload?.category_he || c.payload?.category || '')}${c.payload?.note ? ': ' + esc(c.payload.note) : ''}${c.reply ? `<div class="reply">🤖 ${esc(c.reply)}</div>` : ''}</li>`).join('');
  return `<div class="fb">
    ${d.meta?.rule_version ? `<div class="muted small" dir="ltr">${esc(d.meta.rule_version)}${d.meta?.why?.branch ? ' · ' + esc(d.meta.why.branch) + ' ' + esc(d.meta.why.pivot_date || '') : ''}${d.meta?.bot_before ? ' · edited' : ''}</div>` : ''}
    <div class="fbbtns">${FB.map(([k, l, cls]) => `<button class="${cls} fbb" data-fb="${k}">${l}</button>`).join('')}</div>
    <textarea class="fbnote" rows="1" placeholder="הערה למשוב (לא חובה)"></textarea>
    ${hist ? `<ul class="cmds fbh">${hist}</ul>` : ''}
  </div>`;
}

// ---------------- zone -> Long (Eyal 2026-10-23) ----------------
// When a zone is saved (new or edited) the ticker's Long follows it if it is the BOT's Long (source 'bot'):
// entry / SL are rebuilt from the new zone with the bot rule (botlong.ts = srs_app.bot_drawings.long_from_zone),
// TP stays. His own Long (user / TV / a bot Long he edited) is never moved: only its R:R is re-checked (live PASS).
function liveBoxHtml(r: Row): string {
  const l = liveOf(r); if (!l || !l.gatesOk) return '';
  if (l.status === 'FAIL' && l.fromBelow) return `<section class="wait-box rr-box"><h3>לא ב-PASS · <bdi>${esc(l.why)}</bdi></h3><div class="small">הסגירה השבועית האחרונה מחוץ לאזור הייתה מתחתיו, כלומר המניה חזרה לאזור מלמטה. היא תחזור להיות מעניינת רק אחרי סגירה שבועית מעל האזור וחזרה אליו מלמעלה.</div></section>`;
  if (l.status === 'FAIL') return `<section class="wait-box rr-box"><h3>לא ב-PASS · <bdi>${esc(l.why)}</bdi></h3><div class="small">${l.rr == null ? 'אין לונג פעיל, ולכן ה-R:R לא ידוע.' : 'ה-R:R של הלונג הנוכחי מתחת ל-2.'} הסטטוס מתעדכן מיד כשמשנים אזור או לונג.</div></section>`;
  return '';
}
async function followZone(z: Drawing) {
  if (z.kind !== 'zone' || z.zone_top == null || z.zone_bottom == null) return;
  const t = z.ticker;
  const lg = countedOf(t, 'long');
  if (!lg) { toast('אין לונג — R:R לא ידוע, המניה לא ב-PASS'); refreshLive(); return; }
  if (lg.source !== 'bot') {
    const q = rr(lg.entry, lg.stop, lg.target);
    toast(`הלונג שלך לא זז · R:R ${q == null ? '—' : q.toFixed(2)}${q != null && q < RR_MIN ? ' < 2 → לא PASS' : ''}`);
    refreshLive(); return;
  }
  let daily: Bar[] | null = null;
  try { daily = await loadDaily(t); } catch { daily = null; }
  const b = daily ? botLongFromZone(daily, +z.zone_bottom, +z.zone_top) : null;
  if (!b) { toast('אין נתוני נרות לחישוב הלונג מחדש', true); return; }
  if (b.entry === lg.entry && b.stop === lg.stop) { refreshLive(); return; }
  const now = new Date().toISOString();
  const patch: Partial<Drawing> = {
    entry: b.entry, stop: b.stop,
    meta: { ...(lg.meta || {}), zone_follow: { zone_top: +z.zone_top, zone_bottom: +z.zone_bottom, entry_before: lg.entry,
      stop_before: lg.stop, sl_src: b.sl_src, at: now, rule: 'botlong.ts = srs_app.bot_drawings.long_from_zone' } },
  };
  Object.assign(lg, patch, { updated_at: now });
  const q = rr(lg.entry, lg.stop, lg.target);
  refreshLive();
  await guard(api.updateDrawing(lg.id, patch),
    `לונג הבוט עודכן לפי האזור · R:R ${q == null ? '—' : q.toFixed(2)}${q != null && q < RR_MIN ? ' < 2 → לא PASS' : ''}`);
}
/** Re-render whatever shows status / R:R after a drawing change. */
function refreshLive() {
  if (cv && S.ticker) { renderHeader(); syncChart(); renderPanel(); }
  else if ($('.list')) updateListBody();
}

// ---------------- panel ----------------
function rrText(d: Pick<Drawing, 'entry' | 'stop' | 'target'>) {
  const q = rr(d.entry, d.stop, d.target);
  return q == null ? 'R:R —' : `R:R ${q.toFixed(2)}`;
}
/** Eyal 2026-10-24: "you can remove the zone and Long section, I edit them from the chart" - no level / date inputs any
 *  more; each drawing is one compact read-only line (tap = select it on the chart for dragging) + its remaining actions
 *  (approve / reject / reopen, delete, bot feedback behind 'משוב'). */
function levelsText(d: Drawing): string {
  if (d.kind === 'zone') return `${fmt(d.zone_bottom)}–${fmt(d.zone_top)}`;
  if (d.kind === 'long') return `E ${fmt(d.entry)} · SL ${fmt(d.stop)} · TP ${fmt(d.target)}`;
  return fmt(d.entry);
}
function cardHtml(d: Drawing) {
  const bot = d.source === 'bot';
  const st = { active: bot ? 'פעיל (מאושר אוטומטית)' : 'פעיל', review: 'לבדיקה', approved: 'אושר', rejected: 'נדחה', obsolete: 'ישן', deleted: 'נמחק' }[d.status];
  const kind = { zone: 'אזור', long: 'לונג', line: 'קו', note: 'הערה' }[d.kind];
  const fb = feedbackHtml(d);
  return `<div class="card dline ${d.id === S.selected ? 'sel' : ''} ${bot ? 'bot' : ''}" data-id="${d.id}">
    <div class="ch1">
      <button class="ghost selbtn dsum" title="${d.id === S.selected ? 'בטל בחירה' : 'בחר על הגרף לגרירה'}"><b>${kind}</b> <bdi class="lv" dir="ltr">${levelsText(d)}</bdi>${d.kind === 'long' ? ` <b class="rr" dir="ltr">${rrText(d)}</b>` : ''}</button>
      <span class="badge ${bot ? 'b-review' : d.source === 'tv' ? 'b-tv' : 'b-mine'}">${bot ? 'בוט' : d.source === 'tv' ? 'TV' : d.meta?.bot_before ? 'שלי (מבוט)' : 'שלי'}</span> <span class="badge">${st}</span>
      <span class="acts">
        ${d.status === 'review' ? '<button class="ok small act" data-act="approve">אשר</button><button class="bad small act" data-act="reject">דחה</button>' : ''}
        ${d.status === 'rejected' ? '<button class="small act" data-act="reopen">החזר לבדיקה</button>' : ''}
        ${fb ? '<button class="ghost small fbtog">משוב</button>' : ''}
        ${!bot ? '<button class="ghost small act del" data-act="delete" aria-label="מחק" title="מחק">🗑</button>' : ''}
      </span></div>
    ${d.note ? `<div class="muted small">${esc(d.note)}</div>` : ''}
    ${fb ? `<div class="fbwrap" ${fbOpen.has(d.id) ? '' : 'hidden'}>${fb}</div>` : ''}
  </div>`;
}
const fbOpen = new Set<string>();
function updateCardValues(d: Drawing) {
  const c = $(`.card[data-id="${d.id}"]`); if (!c) return;
  const lv = $('.lv', c); if (lv) lv.textContent = levelsText(d);
  const r = $('.rr', c); if (r) r.textContent = rrText(d);
  const t = S.ticker && S.byT.get(S.ticker); const sz = $('#statusLine'); if (t && sz) sz.outerHTML = statusLineHtml(t);
}
/** Compact read-only status line (was only in the zone / Long cards): live status + reason, R:R and sizing. */
function statusLineHtml(r: Row): string {
  const l = liveOf(r), st = l?.status ?? r.status;
  return `<div id="statusLine" class="statusline small"><span class="badge ${st === 'PASS' ? 'b-pass' : 'b-obs'}">${esc(st || '—')}</span>${l?.why ? ` <bdi>${esc(l.why)}</bdi>` : ''}${sizingHtml(r)}</div>`;
}

let panelDirty = false;
function renderPanel() {
  const p = $('#panel'); if (!p || !S.ticker) return;
  if (p.contains(document.activeElement) && (document.activeElement as HTMLElement).matches('input,textarea')) { panelDirty = true; return; }
  panelDirty = false;
  const t = S.ticker, r = S.byT.get(t);
  const ds = userDrawings(t);
  const note = latestLabel(t, 'note');
  const cmds = S.commands.filter((c) => c.ticker === t).slice(0, 8);
  p.innerHTML = `
    ${r?.data_dup_of ? `<section class="wait-box dupwarn"><div class="small">⚠ נתוני המחיר של המניה זהים ל-<bdi>${esc(r.data_dup_of)}</bdi>, ייתכן שהגרף והשרטוט מחושבים על נתונים שגויים. הבוט יבדוק.</div></section>` : ''}
    ${r ? liveBoxHtml(r) : ''}
    ${r && waitLong(r) ? `<section class="wait-box"><h3>אזהרה על הנר השבועי האחרון (מידע בלבד)</h3><div class="small">${esc(waitLong(r))}</div></section>` : ''}
    <section class="drawsec" id="secDraw">
      ${r ? statusLineHtml(r) : ''}
      ${ds.map(cardHtml).join('') || '<div class="muted small">אין שרטוטים באפליקציה. "+ אזור" / "+ לונג" והקש על הגרף.</div>'}
      ${ds.length ? '<div class="muted small">עריכה: בחר שרטוט (הקשה עליו בגרף או בשורה) וגרור את הקווים.</div>' : ''}
    </section>
    ${researchHtml(S.research.get(t), S.ui.researchOpen !== false)}
    ${fibPanelHtml(r)}
    <section class="unfitsec" id="secUnfit">
      <h3>לא מתאימה לשיטה</h3>
      ${unfitHtml(t)}
    </section>
    <section id="secNote">
      <h3>הערה</h3>
      <textarea id="note" rows="2" placeholder="הערה חופשית">${esc(note?.value || '')}</textarea>
    </section>
    <section id="secCmd">
      <h3>פקודה לבוט <span class="muted small">(${esc(t)})</span></h3>
      <div class="cmd"><textarea id="cmd" rows="2" placeholder="למשל: תשרטט אזור חדש, תבדוק דוחות…"></textarea><button id="sendCmd" class="primary">שלח</button></div>
      <ul class="cmds">${cmds.map((c) => `<li><span class="badge ${c.status === 'done' ? 'b-pass' : c.status === 'error' ? 'b-obs' : 'b-review'}">${{ pending: 'ממתין', done: 'בוצע', error: 'שגיאה' }[c.status]}</span> ${esc(c.text)}${c.reply ? `<div class="reply">${esc(c.reply)}</div>` : ''}</li>`).join('')}</ul>
    </section>
    ${r ? `<section id="secData"><h3>נתוני סריקה</h3><div class="kv small" dir="ltr">
      status ${esc(liveOf(r)?.status ?? r.status)}${liveOf(r) && liveOf(r)!.status !== r.status ? ` (export ${esc(r.status)})` : ''} · R:R ${fmt(liveRR(r))} · zone dist ${fmt(r.tv_zone_dist_atr, 1)} ATR · wATR ${fmt(r.weekly_atr)}<br/>
      ${r.earnings_none ? '<span dir="rtl">אין דוחות</span>' : `earnings ${earnShort(r).replace(/^earn /, '') || '?'}`} ${r.tv_stale ? `· stale: ${esc(r.tv_stale)}` : ''}<br/>
      ${r.badges.includes('hammer') ? `${esc(r.last_week_reversal_kind)} E ${fmt(r.hammer_entry)} SL ${fmt(r.hammer_sl)} TP ${fmt(r.hammer_tp)} R:R ${fmt(r.hammer_rr)} calm ${r.hammer_calm_weeks ?? '?'}w` : ''}
      ${r.tradingview_url ? `<br/><a href="${esc(r.tradingview_url)}" target="_blank" rel="noopener">TradingView ↗</a>` : ''}</div></section>` : ''}
    <div class="spacer"></div>`;
  syncJumps();
  const rs = $('#research', p) as HTMLDetailsElement | null; if (rs) rs.ontoggle = () => { S.ui.researchOpen = rs.open; saveUi(); };
  const fa = $('#fibAuto', p); if (fa) fa.onclick = () => { if (S.ticker) saveFibManual(S.ticker, null); };

  p.querySelectorAll<HTMLElement>('.card[data-id]').forEach((c) => {
    const id = c.dataset.id!;
    $('.selbtn', c)?.addEventListener('click', () => { S.selected = S.selected === id ? null : id; syncChart(); renderPanel(); });
    $('.fbtog', c)?.addEventListener('click', () => { fbOpen.has(id) ? fbOpen.delete(id) : fbOpen.add(id); const w = $('.fbwrap', c); if (w) w.hidden = !fbOpen.has(id); });
    c.querySelectorAll<HTMLButtonElement>('.fbb').forEach((b) => (b.onclick = () => {
      const d = S.drawings.get(id); if (!d) return;
      const note = (c.querySelector('.fbnote') as HTMLTextAreaElement | null)?.value.trim() || '';
      sendFeedback(d, b.dataset.fb as FeedbackCategory, note);
    }));
    c.querySelectorAll<HTMLButtonElement>('.act').forEach((b) => (b.onclick = async () => {
      const a = b.dataset.act!;
      if (a === 'delete') {
        if (!confirm('למחוק את השרטוט?')) return;
        S.drawings.delete(id); if (S.selected === id) S.selected = null; renderHeader(); syncChart(); renderPanel();
        await guard(api.deleteDrawing(id), 'נמחק');
      } else {
        const status = a === 'approve' ? 'approved' : a === 'reject' ? 'rejected' : 'review';
        const d = S.drawings.get(id); if (d) d.status = status; renderHeader(); syncChart(); renderPanel();
        await guard(api.updateDrawing(id, { status }), status === 'approved' ? 'אושר' : status === 'rejected' ? 'נדחה' : 'הוחזר');
      }
    }));
  });
  bindUnfit($('.unfitsec', p)!, t);
  const noteEl = $('#note') as HTMLTextAreaElement;
  noteEl.addEventListener('change', async () => {
    const l: Label = { ticker: t, label: 'note', value: noteEl.value, note: null, asof: today(), created_at: new Date().toISOString() };
    S.labels = S.labels.filter((x) => !(x.ticker === t && x.label === 'note' && x.asof === l.asof)); S.labels.push(l);
    await guard(api.upsertLabel(l), 'ההערה נשמרה');
  });
  noteEl.addEventListener('blur', () => setTimeout(() => { if (panelDirty) renderPanel(); }, 0));
  $('#sendCmd')!.onclick = async () => {
    const el = $('#cmd') as HTMLTextAreaElement; const txt = el.value.trim(); if (!txt) return;
    const c = await guard(api.addCommand(t, txt), 'נשלח לבוט');
    if (c) { el.value = ''; if (!S.commands.some((x) => x.id === c.id)) S.commands.unshift(c); el.blur(); renderPanel(); }
  };
}

// ---------------- message to the bot from any page (Eyal 2026-10-27: "can't send a message to the bot" on mobile) ----------------
// Floating 💬 button on every page. On a stock page it jumps to that stock's 'פקודה לבוט' box; elsewhere it opens a sheet
// for a general message (commands row with ticker = null, same table / trigger as the per-stock box).
const botFab = document.createElement('button');
botFab.id = 'botFab'; botFab.className = 'fab primary'; botFab.setAttribute('aria-label', 'הודעה לבוט'); botFab.textContent = '💬'; botFab.hidden = true;
const botSheet = document.createElement('div');
botSheet.id = 'botSheet'; botSheet.className = 'sheet'; botSheet.hidden = true;
document.body.append(botFab, botSheet);
function syncBotFab() {
  const ok = !!S.email && S.email.toLowerCase() === OWNER_EMAIL && S.loaded;
  botFab.hidden = !ok; if (!ok || location.hash.startsWith('#/t/')) botSheet.hidden = true;
}
function botListHtml() {
  const cs = S.commands.filter((c) => !c.ticker).slice(0, 8);
  return cs.map((c) => `<li><span class="badge ${c.status === 'done' ? 'b-pass' : c.status === 'error' ? 'b-obs' : 'b-review'}">${{ pending: 'ממתין', done: 'בוצע', error: 'שגיאה' }[c.status]}</span> ${esc(c.text)}${c.reply ? `<div class="reply">${esc(c.reply)}</div>` : ''}</li>`).join('')
    || '<li class="muted small">אין עדיין הודעות כלליות. הודעה על מניה מסוימת: מעמוד המניה.</li>';
}
function openBotSheet() {
  botSheet.innerHTML = `<div class="sh-head"><b>הודעה לבוט</b><button id="botClose" class="ghost small" aria-label="סגור">✕</button></div>
    <div class="cmd"><textarea id="gcmd" rows="3" placeholder="למשל: תעדכן את הכללים, תבדוק את כל המניות שבמעקב…"></textarea><button id="gsend" class="primary">שלח</button></div>
    <ul class="cmds" id="gcmds">${botListHtml()}</ul>`;
  botSheet.hidden = false;
  $('#botClose', botSheet)!.onclick = () => { botSheet.hidden = true; };
  $('#gsend', botSheet)!.onclick = async () => {
    const el = $('#gcmd', botSheet) as HTMLTextAreaElement; const txt = el.value.trim(); if (!txt) return;
    const c = await guard(api.addCommand(null, txt), 'נשלח לבוט');
    if (c) { el.value = ''; if (!S.commands.some((x) => x.id === c.id)) S.commands.unshift(c); $('#gcmds', botSheet)!.innerHTML = botListHtml(); }
  };
}
botFab.onclick = () => {
  if (cv && S.ticker && document.getElementById('secCmd')) { jumpTo('secCmd'); return; }
  if (botSheet.hidden) openBotSheet(); else botSheet.hidden = true;
};

// ---------------- realtime ----------------
function onChange(table: Table, ev: string, row: any, old: any) {
  if (table === 'positions') { loadPositions(); return; }
  if (table === 'drawings') {
    if (ev === 'DELETE' || row?.status === 'deleted') S.drawings.delete(old?.id ?? row?.id); else if (row) S.drawings.set(row.id, row);
  } else if (table === 'labels') {
    if (ev === 'DELETE') S.labels = S.labels.filter((l) => !(l.ticker === old?.ticker && l.label === old?.label && l.asof === old?.asof));
    else if (row) { S.labels = S.labels.filter((l) => !(l.ticker === row.ticker && l.label === row.label && l.asof === row.asof)); S.labels.push(row); }
  } else if (table === 'watchlist') {
    if (ev === 'DELETE') S.watch.delete(old?.ticker); else if (row) S.watch.set(row.ticker, row);
  } else if (table === 'commands') {
    if (ev === 'DELETE') S.commands = S.commands.filter((c) => c.id !== old?.id);
    else if (row) { const i = S.commands.findIndex((c) => c.id === row.id); if (i >= 0) S.commands[i] = row; else S.commands.unshift(row); }
  }
  if (table === 'commands' && !botSheet.hidden) { const g = $('#gcmds', botSheet); if (g) g.innerHTML = botListHtml(); }
  if (cv && S.ticker) { renderHeader(); syncChart(); if (table === 'labels') applyIndicators(); renderPanel(); }
  else if (!location.hash.startsWith('#/t/') && $('.list')) updateListBody();
}

// ---------------- boot ----------------
async function loadAll() {
  if (api.demo && !(window as any).__seeded) { (window as any).__seeded = true; (api as any).seedTv(await loadTv()); }
  const [idx, ds, ls, cs, ws] = await Promise.all([
    loadIndex(), api.loadDrawings(), api.loadLabels(), api.loadCommands(), api.loadWatch(),
  ]);
  S.rows = idx.rows; S.byT = new Map(idx.rows.map((r) => [r.ticker, r])); S.reportDate = idx.report_date;
  S.watch = new Map(ws.map((w) => [w.ticker, w])); S.drawings = new Map(ds.map((d) => [d.id, d])); S.labels = ls; S.commands = cs;
  S.loaded = true;
  loadPositions();
  loadResearch();
}
/** overviews: any ticker with a ticker_research row (PASS overviews + starred research); failure = no section */
async function loadResearch() {
  try { S.research = new Map((await api.loadResearch()).map((x) => [x.ticker, x])); } catch { return; }
  if (cv && S.ticker) renderPanel();
}

// ---------------- open positions bar (Eyal 2026-10-24): always on top of every page ----------------
const PB_LS = 'srs_posbar_collapsed';
const posbar = document.getElementById('posbar')!;
const sgn = (x: number, d = 2) => (x >= 0 ? '+' : '−') + Math.abs(x).toFixed(d);
const usdS = (x: number) => (x >= 0 ? '+' : '−') + '$' + Math.abs(x).toFixed(2);
const ud = (x: number | null) => (x == null ? '' : x >= 0 ? 'up' : 'dn');
let quoteBusy = false;
async function loadPositions() {
  try { S.positions = await api.loadPositions(); } catch { S.positions = []; }
  renderPosBar();
  await refreshQuotes();
}
async function refreshQuotes() {
  if (!S.positions.length || quoteBusy) return;
  quoteBusy = true; posbar.classList.add('busy');
  try { S.quotes = await fetchQuotes(S.positions); } finally { quoteBusy = false; posbar.classList.remove('busy'); }
  renderPosBar();
}
function renderPosBar() {
  const show = !!S.email && S.email.toLowerCase() === OWNER_EMAIL && S.loaded && S.positions.length > 0;
  posbar.hidden = !show;
  document.body.classList.toggle('has-pb', show);
  if (!show) { document.documentElement.style.setProperty('--pb', '0px'); return; }
  const collapsed = localStorage.getItem(PB_LS) === '1';
  const cs = S.positions.map((p) => calcPosition(p, S.quotes.get(p.ticker)?.price ?? null));
  const tot = totals(cs);
  const labels = [...new Set(S.positions.map((p) => quoteLabel(S.quotes.get(p.ticker))))];
  const rows = S.positions.map((p, i) => {
    const c = cs[i], q = S.quotes.get(p.ticker), lab = quoteLabel(q);
    return `<a class="pb-row" href="#/t/${encodeURIComponent(p.ticker)}" data-t="${esc(p.ticker)}" title="${esc(lab)}">
      <b class="pb-tk" dir="ltr">${esc(p.ticker)}</b>
      <span class="pb-q" dir="ltr">${fmt(p.qty, p.qty % 1 ? 2 : 0)} × ${fmt(p.entry_price)}</span>
      <span class="pb-px" dir="ltr" data-v="${c.price ?? ''}">${c.price == null ? '—' : fmt(c.price)}${q && q.src !== 'cnbc' ? `<small>${q.src === 'tv' ? ' מושהה' : ' סגירה'}</small>` : ''}${q?.ext ? `<small> ${q.ext.kind === 'PRE_MKT' ? 'pre' : 'AH'} ${fmt(q.ext.price)}</small>` : ''}</span>
      <span class="pb-pl ${ud(c.pl)}" dir="ltr" data-v="${c.pl ?? ''}">${c.pl == null ? '—' : `${usdS(c.pl)} (${sgn(c.plPct!)}%)`}</span>
      <span class="pb-r ${ud(c.r)}" dir="ltr" data-v="${c.r ?? ''}">${c.r == null ? '' : sgn(c.r) + 'R'}</span>
      <span class="pb-sl" dir="ltr" data-v="${c.toStopPct ?? ''}">${p.stop == null ? '' : `SL ${fmt(p.stop)}${c.toStopPct == null ? '' : ` (${sgn(c.toStopPct, 1)}%)`}`}</span>
      <span class="pb-tp" dir="ltr" data-v="${c.toTgtPct ?? ''}">${p.target == null ? '' : `TP ${fmt(p.target)}${c.toTgtPct == null ? '' : ` (${sgn(c.toTgtPct, 1)}%)`}`}</span>
    </a>`;
  }).join('');
  posbar.innerHTML = `<div class="pb-head">
      <button class="pb-tog ghost small" id="pbTog" aria-expanded="${!collapsed}">${collapsed ? '▸' : '▾'} פוזיציות (${S.positions.length})</button>
      <span class="pb-tot ${ud(tot.pl)}" dir="ltr" data-pl="${tot.pl ?? ''}">${tot.pl == null ? '—' : `${usdS(tot.pl)} (${sgn(tot.plPct!)}%)${tot.r != null ? ` · ${sgn(tot.r)}R` : ''}`}</span>
      <span class="pb-src muted">${esc(labels.join(' / '))}</span>
      <button class="ghost small pb-ref" id="pbRef" aria-label="רענן מחיר">↻</button>
    </div>
    <div class="pb-rows" ${collapsed ? 'hidden' : ''}>${rows}</div>`;
  $('#pbTog', posbar)!.onclick = () => { localStorage.setItem(PB_LS, collapsed ? '0' : '1'); renderPosBar(); };
  $('#pbRef', posbar)!.onclick = () => refreshQuotes();
  document.documentElement.style.setProperty('--pb', posbar.offsetHeight + 'px');
}
new ResizeObserver(() => { if (!posbar.hidden) document.documentElement.style.setProperty('--pb', posbar.offsetHeight + 'px'); }).observe(posbar);
setInterval(() => { if (document.visibilityState === 'visible') refreshQuotes(); }, 60_000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshQuotes(); });

let subscribed = false;
let loading: Promise<void> | null = null;
async function onLogin(email: string | null) {
  S.email = email;
  if (email && email.toLowerCase() === OWNER_EMAIL && !S.loaded) {
    route();
    loading ??= loadAll().finally(() => { loading = null; });
    try { await loading; } catch (e: any) { app.innerHTML = `<div class="center">שגיאה בטעינה: ${esc(e?.message || e)}</div>`; return; }
    if (!subscribed) { api.subscribe(onChange); subscribed = true; }
  }
  if (!email) { S.loaded = false; destroyChart(); S.ticker = null; }
  route();
  renderPosBar();
}

api.onAuth((e) => { if (e !== S.email || (e && !S.loaded)) onLogin(e); });
api.session().then((s) => onLogin(s.email));

if ('serviceWorker' in navigator && import.meta.env.PROD && !api.demo) {
  navigator.serviceWorker.register(import.meta.env.BASE_URL + 'sw.js', { updateViaCache: 'none' }).then((r) => r.update()).catch(() => {});
}
// expose for tests / debugging
(window as any).__srs = { S, api, factsOf, setChip: (c: string) => { S.ui.f = {}; if (c !== "all") applyChip(S.ui.f, c); saveUi(); if ($(".list")) renderList(); }, refreshQuotes, renderPosBar, atr, botLongFromZone, loadDaily, liveOf, zoneDistOf, fibOfCur, fibManual, snapWick, applyIndicators, filtered, badgesOf, longLevels, sizeLong, maxRiskUsd, refreshLive, get cv() { return cv; } };

// ---------------- new build available (2026-10-24): an open tab / home-screen app picks up a new deploy ----------------
// index.html is cached up to 10 min by GitHub Pages and a tab can stay open for days: compare the bundle name in a fresh
// index.html with the running one (on focus and every 5 min) and offer a reload.
const myBundle = (document.querySelector('script[type="module"][src*="/assets/index-"]') as HTMLScriptElement | null)?.src.split('/').pop() || '';
async function checkNewBuild() {
  if (!myBundle || !import.meta.env.PROD) return;
  try {
    const html = await (await fetch(import.meta.env.BASE_URL + 'index.html?v=' + Date.now(), { cache: 'no-store' })).text();
    const m = html.match(/assets\/(index-[\w-]+\.js)/);
    if (m && m[1] !== myBundle && !document.getElementById('newBuild')) {
      const b = document.createElement('button');
      b.id = 'newBuild'; b.className = 'newbuild primary'; b.textContent = 'יש גרסה חדשה · רענן';
      b.onclick = () => location.reload();
      document.body.appendChild(b);
    }
  } catch { /* offline */ }
}
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkNewBuild(); });
setInterval(checkNewBuild, 5 * 60 * 1000);
setTimeout(checkNewBuild, 4000);
