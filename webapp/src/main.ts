import './styles.css';
import { makeApi, OWNER_EMAIL, type Table } from './api';
import { ChartView } from './chart';
import { atr, loadDaily, loadIndex, loadTv, rr, toWeekly } from './data';
import type { Bar, Command, Drawing, Label, Row, Watch } from './types';

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
  ui: { q: '', chip: 'all', sort: 'default', tf: 'W' as 'W' | 'D', niWeeks: 8 as number, ...JSON.parse(localStorage.getItem(LS) || '{}') },
  ticker: null as string | null,
  selected: null as string | null,
  tap: null as null | { kind: 'zone' | 'long'; pts: number[]; date: string | null },
  loaded: false,
};
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
  pass: ['PASS', 'b-pass'], needs_drawing: ['צריך שרטוט', 'b-need'], review: ['לבדיקה', 'b-review'],
  obsolete: ['לא עדכני', 'b-obs'], hammer: ['פטיש', 'b-hammer'], position: ['פוזיציה', 'b-pos'], off_screen: ['מחוץ לסריקה', 'b-off'],
  watch: ['מעקב', 'b-watch'], ni: ['לא מעניינת', 'b-ni'], nodata: ['אין נתונים עדיין', 'b-off'],
};
const CHIPS: [string, string][] = [
  ['all', 'הכל'], ['pass', 'PASS'], ['needs_drawing', 'צריך שרטוט'], ['review', 'לבדיקה'], ['obsolete', 'לא עדכני'],
  ['hammer', 'פטיש'], ['position', 'פוזיציה'], ['watch', '★ מעקב'], ['mine', 'שרטוטים'], ['commands', 'פקודות'], ['ni', 'לא מעניינות'],
];
const badgeHtml = (b: string) => (BADGES[b] ? `<span class="badge ${BADGES[b][1]}">${BADGES[b][0]}</span>` : '');

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
  const b = [...r.badges];
  if (isWatched(r.ticker)) b.unshift('watch');
  if (isNi(r.ticker)) b.unshift('ni');
  return b;
}
const normT = (q: string) => q.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '');
async function toggleWatch(t: string) {
  if (isWatched(t)) { S.watch.delete(t); refreshViews(); await guard(api.removeWatch(t), 'הוסר מהמעקב'); }
  else { S.watch.set(t, { ticker: t, note: null }); refreshViews(); await guard(api.addWatch(t), 'נוסף למעקב ★'); }
}
async function setNi(t: string, weeks: number | null, on: boolean) {
  let until: string | null = null;
  if (on && weeks) { const d = new Date(today() + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + weeks * 7); until = d.toISOString().slice(0, 10); }
  const l: Label = { ticker: t, label: 'not_interesting', value: on ? 'yes' : 'no', note: null, asof: today(), until, created_at: new Date().toISOString() };
  S.labels = S.labels.filter((x) => !(x.ticker === t && x.label === l.label && x.asof === l.asof)); S.labels.push(l);
  refreshViews();
  await guard(api.upsertLabel(l), on ? 'סומן לא מעניינת' : 'בוטל סימון');
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

function filtered(): Row[] {
  const q = S.ui.q.trim().toUpperCase();
  let rows = allRows().filter((r) => {
    if (q && !r.ticker.includes(q)) return false;
    const c = S.ui.chip;
    if (c === 'ni') return isNi(r.ticker);
    if (c === 'watch') return isWatched(r.ticker);
    if (isNi(r.ticker)) return false; // hidden unless the 'לא מעניינות' chip is on
    if (c === 'all') return true;
    if (c === 'mine') return userDrawings(r.ticker).length > 0;
    if (c === 'commands') return S.commands.some((x) => x.ticker === r.ticker);
    return r.badges.includes(c);
  });
  const num = (x: unknown) => (x == null ? -Infinity : +x);
  const s = S.ui.sort;
  if (s === 'ticker') rows = [...rows].sort((a, b) => a.ticker.localeCompare(b.ticker));
  else if (s === 'rr') rows = [...rows].sort((a, b) => num(b.tv_rr) - num(a.tv_rr));
  else if (s === 'zone') rows = [...rows].sort((a, b) => (a.tv_zone_dist_atr == null ? 1e9 : +a.tv_zone_dist_atr) - (b.tv_zone_dist_atr == null ? 1e9 : +b.tv_zone_dist_atr));
  else if (s === 'hammer') rows = [...rows].sort((a, b) => num(b.hammer_score) - num(a.hammer_score));
  else {
    const rank = (r: Row) => (r.badges.includes('position') ? 0 : isWatched(r.ticker) ? 0.5 : r.badges.includes('position') ? 0 : r.badges.includes('pass') ? 1 : r.badges.includes('review') ? 2 : r.badges.includes('hammer') ? 3 : r.badges.includes('needs_drawing') ? 4 : 5);
    rows = [...rows].sort((a, b) => rank(a) - rank(b) || num(b.tv_rr) - num(a.tv_rr) || a.ticker.localeCompare(b.ticker));
  }
  return rows;
}

// ---------------- routing ----------------
function route() {
  if (!S.email) return renderLogin();
  if (S.email.toLowerCase() !== OWNER_EMAIL) return renderDenied();
  if (!S.loaded) { app.innerHTML = '<div class="center muted">טוען…</div>'; return; }
  const m = location.hash.match(/^#\/t\/([^/?]+)/);
  if (m) openTicker(decodeURIComponent(m[1]).toUpperCase());
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
  const chips = CHIPS.map(([k, t]) => `<button class="chip ${S.ui.chip === k ? 'on' : ''}" data-chip="${k}">${t}</button>`).join('');
  app.innerHTML = `
  <header class="top">
    <div class="title">Retest <span class="muted small">${esc(S.reportDate || '')}</span></div>
    <button id="logout" class="ghost small">יציאה</button>
  </header>
  <div class="filters">
    <input id="q" type="search" dir="ltr" placeholder="חיפוש טיקר" value="${esc(S.ui.q)}" autocapitalize="characters" />
    <div class="chips">${chips}</div>
    <div class="sortrow"><span class="muted small">${rows.length} מניות</span>
      <select id="sort">
        ${[['default', 'סדר: עדיפות'], ['rr', 'R:R TV'], ['zone', 'קרבה לאזור'], ['hammer', 'ציון פטיש'], ['ticker', 'א-ב']].map(([v, t]) => `<option value="${v}" ${S.ui.sort === v ? 'selected' : ''}>${t}</option>`).join('')}
      </select></div>
  </div>
  <ul class="list">${listInner(rows)}</ul>`;
  const q = $('#q') as HTMLInputElement;
  q.oninput = () => { S.ui.q = q.value; saveUi(); updateListBody(); };
  app.querySelectorAll<HTMLButtonElement>('.chip').forEach((b) => (b.onclick = () => { S.ui.chip = b.dataset.chip!; saveUi(); renderList(); }));
  ($('#sort') as HTMLSelectElement).onchange = (e) => { S.ui.sort = (e.target as HTMLSelectElement).value; saveUi(); renderList(); };
  $('#logout')!.onclick = () => api.signOut();
  bindRows();
  const y = sessionStorage.getItem('srs-scroll'); if (y) window.scrollTo(0, +y);
}
function updateListBody() {
  const rows = filtered();
  $('.list')!.innerHTML = listInner(rows);
  $('.sortrow .small')!.textContent = `${rows.length} מניות`;
  bindRows();
}
function listInner(rows: Row[]) {
  const q = normT(S.ui.q);
  const add = q && !allRows().some((r) => r.ticker === q)
    ? `<li class="addrow"><button class="primary" id="addWatch" data-t="${esc(q)}">★ הוסף ${esc(q)} למעקב</button><div class="muted small">לא ברשימת המועמדים. נרות יתווספו בריצה הלילית.</div></li>` : '';
  return add + (rows.map(rowHtml).join('') || (add ? '' : '<li class="muted center">אין תוצאות</li>'));
}
function bindRows() {
  const aw = $('#addWatch') as HTMLButtonElement | null;
  if (aw) aw.onclick = async () => { const t = aw.dataset.t!; await toggleWatch(t); S.ui.q = ''; saveUi(); location.hash = '#/t/' + t; };
  app.querySelectorAll<HTMLButtonElement>('.row .star').forEach((b) => (b.onclick = (e) => { e.stopPropagation(); toggleWatch(b.dataset.star!); }));
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
  ].join('');
  const dist = r.tv_zone_dist_atr != null ? `${fmt(r.tv_zone_dist_atr, 1)} ATR` : '';
  return `<li class="row" data-t="${esc(r.ticker)}">
    <div class="r1"><span><button class="star ${isWatched(r.ticker) ? 'on' : ''}" data-star="${esc(r.ticker)}" aria-label="מעקב">${isWatched(r.ticker) ? '★' : '☆'}</button><b dir="ltr">${esc(r.ticker)}</b></span><span class="px" dir="ltr">${fmt(r.current_price)}</span></div>
    <div class="r2">${badgesOf(r).map(badgeHtml).join('')}${extra}</div>
    <div class="r3 muted small" dir="ltr">${r.tv_rr != null ? `R:R ${fmt(r.tv_rr)}` : ''} ${dist ? '· ' + dist : ''} ${r.badges.includes('hammer') ? `· hammer R:R ${fmt(r.hammer_rr)}` : ''} ${r.days_to_earnings != null ? `· earn ${r.days_to_earnings}d` : ''}</div>
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
      <div class="tk"><b id="tk" dir="ltr"></b> <span id="tkpx" class="muted small" dir="ltr"></span><div id="tkb" class="tkb"></div></div>
      <button id="star" class="ghost icon star" aria-label="מעקב">☆</button>
      <button id="niBtn" class="ghost small nib" aria-label="לא מעניינת">🚫</button>
      <button id="prev" class="ghost icon" aria-label="הקודם">‹</button>
      <button id="next" class="ghost icon" aria-label="הבא">›</button>
    </header>
    <div id="chart" class="chartwrap" dir="ltr"><div id="nodata" class="nodata" hidden>אין עדיין נתוני נרות למניה הזו.<br/>הם יתווספו בריצה הלילית הבאה.</div></div>
    <div class="tools" id="tools">
      <div class="seg"><button data-tf="W">שבועי</button><button data-tf="D">יומי</button></div>
      <button id="addZone">+ אזור</button>
      <button id="addLong">+ לונג</button>
    </div>
    <div id="hint" class="hint" hidden></div>
    <div class="panel" id="panel"></div>
  </div>`;
  cv = new ChartView($('#chart')!, {
    onSelect: (id) => { S.selected = id; syncChart(); renderPanel(); },
    onDragMove: (d) => updateCardValues(d),
    onDragEnd: async (id, patch) => {
      const d = S.drawings.get(id); if (d) Object.assign(d, patch);
      renderPanel();
      await guard(api.updateDrawing(id, patch));
    },
    onTap: (price, date) => onChartTap(price, date),
  });
  $('#back')!.onclick = () => { location.hash = '#/'; };
  $('#star')!.onclick = () => S.ticker && toggleWatch(S.ticker);
  $('#niBtn')!.onclick = () => { if (!S.ticker) return; isNi(S.ticker) ? setNi(S.ticker, null, false) : setNi(S.ticker, S.ui.niWeeks ?? 8, true); };
  $('#prev')!.onclick = () => go(-1);
  $('#next')!.onclick = () => go(1);
  app.querySelectorAll<HTMLButtonElement>('[data-tf]').forEach((b) => (b.onclick = () => { S.ui.tf = b.dataset.tf as 'W' | 'D'; saveUi(); applyBars(); }));
  $('#addZone')!.onclick = () => startTap('zone');
  $('#addLong')!.onclick = () => startTap('long');
  swipe($('#chhead')!); swipe($('#panel')!); swipe($('#tools')!);
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
  } catch (e: any) {
    if (seq !== loadSeq) return;
    curBars = null; cv?.setBars([], 0); ($('#nodata') as HTMLElement).hidden = false;
  }
  // prefetch neighbours for fast swipes
  for (const d of [1, -1] as const) { const n = neighbor(d); if (n) loadDaily(n).catch(() => {}); }
}

function renderHeader() {
  const t = S.ticker; if (!t) return;
  const r = S.byT.get(t) || allRows().find((x) => x.ticker === t) || { ticker: t, status: '', badges: [] };
  $('#tk')!.textContent = t;
  $('#tkpx')!.textContent = r.current_price != null ? fmt(r.current_price) : '';
  $('#tkb')!.innerHTML = badgesOf(r as Row).filter((b) => b !== 'watch').map(badgeHtml).join('');
  const st = $('#star')!; st.textContent = isWatched(t) ? '★' : '☆'; st.classList.toggle('on', isWatched(t));
  $('#niBtn')!.classList.toggle('on', isNi(t));
}

function applyBars() {
  app.querySelectorAll<HTMLButtonElement>('[data-tf]').forEach((b) => b.classList.toggle('on', b.dataset.tf === S.ui.tf));
  if (!cv || !curBars) return;
  const bars = S.ui.tf === 'W' ? curBars.weekly : curBars.daily;
  syncChart();
  cv.setBars(bars, S.ui.tf === 'W' ? 110 : 160);
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
    row = { ticker: S.ticker, kind: 'long', entry: a, stop: b, target: Math.round((a + 2 * (a - b)) * 100) / 100, t_start: t.date, source: 'user', status: 'active' };
  }
  S.tap = null; renderHint();
  const d = await guard(api.insertDrawing(row), 'נשמר');
  if (d) { S.drawings.set(d.id, d); S.selected = d.id; syncChart(); renderPanel(); }
}

// ---------------- panel ----------------
function numInput(d: Drawing, f: keyof Drawing, label: string, ro: boolean) {
  return `<label class="ni"><span>${label}</span><input dir="ltr" type="number" inputmode="decimal" step="0.01" data-f="${f}" value="${d[f] ?? ''}" ${ro ? 'disabled' : ''}/></label>`;
}
function dateInput(d: Drawing, f: 't_start' | 't_end', label: string, ro: boolean) {
  return `<label class="ni"><span>${label}</span><input dir="ltr" type="date" data-f="${f}" value="${d[f] ?? ''}" ${ro ? 'disabled' : ''}/></label>`;
}
function rrText(d: Pick<Drawing, 'entry' | 'stop' | 'target'>) {
  const q = rr(d.entry, d.stop, d.target);
  return q == null ? 'R:R —' : `R:R ${q.toFixed(2)}`;
}
function cardHtml(d: Drawing) {
  const bot = d.source === 'bot';
  const ro = false;
  const st = { active: 'פעיל', review: 'לבדיקה', approved: 'אושר', rejected: 'נדחה', obsolete: 'ישן', deleted: 'נמחק' }[d.status];
  const kind = { zone: 'אזור', long: 'לונג', line: 'קו', note: 'הערה' }[d.kind];
  let body = '';
  if (d.kind === 'zone') body = numInput(d, 'zone_top', 'עליון', ro) + numInput(d, 'zone_bottom', 'תחתון', ro) + dateInput(d, 't_start', 'מתאריך', ro);
  else if (d.kind === 'long') body = numInput(d, 'entry', 'כניסה', ro) + numInput(d, 'stop', 'סטופ', ro) + numInput(d, 'target', 'יעד', ro) + dateInput(d, 't_start', 'מתאריך', ro);
  else if (d.kind === 'line') body = numInput(d, 'entry', 'מחיר', ro);
  const risk = d.kind === 'long' && d.entry != null && d.stop != null ? `<span class="muted small" dir="ltr">risk ${fmt(+d.entry - +d.stop)}</span>` : '';
  return `<div class="card ${d.id === S.selected ? 'sel' : ''} ${bot ? 'bot' : ''}" data-id="${d.id}">
    <div class="ch1"><b>${kind}</b> <span class="badge ${bot ? 'b-review' : d.source === 'tv' ? 'b-tv' : 'b-mine'}">${bot ? 'בוט' : d.source === 'tv' ? 'TV' : 'שלי'}</span> <span class="badge">${st}</span>
      ${d.kind === 'long' ? `<b class="rr" dir="ltr">${rrText(d)}</b> ${risk}` : ''}
      <button class="ghost small selbtn">${d.id === S.selected ? 'בטל בחירה' : 'בחר / גרור'}</button></div>
    <div class="grid">${body}</div>
    ${d.note ? `<div class="muted small">${esc(d.note)}</div>` : ''}
    <div class="acts">
      ${d.status === 'review' ? '<button class="ok act" data-act="approve">אשר</button><button class="bad act" data-act="reject">דחה</button>' : ''}
      ${d.status === 'rejected' ? '<button class="act" data-act="reopen">החזר לבדיקה</button>' : ''}
      ${!bot ? '<button class="bad act" data-act="delete">מחק</button>' : ''}
    </div>
  </div>`;
}
function updateCardValues(d: Drawing) {
  const c = $(`.card[data-id="${d.id}"]`); if (!c) return;
  c.querySelectorAll<HTMLInputElement>('input[data-f]').forEach((i) => { const v = (d as any)[i.dataset.f!]; i.value = v ?? ''; });
  const r = $('.rr', c); if (r) r.textContent = rrText(d);
}

let panelDirty = false;
function renderPanel() {
  const p = $('#panel'); if (!p || !S.ticker) return;
  if (p.contains(document.activeElement) && (document.activeElement as HTMLElement).matches('input,textarea')) { panelDirty = true; return; }
  panelDirty = false;
  const t = S.ticker, r = S.byT.get(t);
  const ni = latestLabel(t, 'not_interesting'), niOn = isNi(t);
  const ds = userDrawings(t);
  const tech = latestLabel(t, 'technical'), note = latestLabel(t, 'note');
  const cmds = S.commands.filter((c) => c.ticker === t).slice(0, 8);
  p.innerHTML = `
    <section>
      <h3>שרטוטים</h3>
      ${ds.map(cardHtml).join('') || '<div class="muted small">אין שרטוטים באפליקציה. "+ אזור" / "+ לונג" והקש על הגרף.</div>'}
    </section>
    <section>
      <h3>לא מעניינת</h3>
      <div class="row2 ni">${niOn
        ? `<span class="badge b-ni">לא מעניינת ${ni?.until ? 'עד ' + esc(ni.until) : 'לתמיד'}</span><button id="niOff" class="ok">בטל סימון</button>`
        : `<select id="niWeeks">${[[4, '4 שבועות'], [8, '8 שבועות'], [12, '12 שבועות'], [0, 'לתמיד']].map(([v, l]) => `<option value="${v}" ${(S.ui.niWeeks ?? 8) === v ? 'selected' : ''}>${l}</option>`).join('')}</select><button id="niOn" class="bad">סמן לא מעניינת</button>`}</div>
    </section>
    <section>
      <h3>תיוג</h3>
      <div class="row2"><span>טכנית?</span>
        <button class="lab ${tech?.value === 'yes' ? 'ok on' : ''}" data-v="yes">כן</button>
        <button class="lab ${tech?.value === 'no' ? 'bad on' : ''}" data-v="no">לא</button>
        ${tech ? `<span class="muted small">${esc(tech.asof)}</span>` : ''}</div>
      <textarea id="note" rows="2" placeholder="הערה חופשית">${esc(note?.value || '')}</textarea>
    </section>
    <section>
      <h3>פקודה לבוט</h3>
      <div class="cmd"><textarea id="cmd" rows="2" placeholder="למשל: תשרטט אזור חדש, תבדוק דוחות…"></textarea><button id="sendCmd" class="primary">שלח</button></div>
      <ul class="cmds">${cmds.map((c) => `<li><span class="badge ${c.status === 'done' ? 'b-pass' : c.status === 'error' ? 'b-obs' : 'b-review'}">${{ pending: 'ממתין', done: 'בוצע', error: 'שגיאה' }[c.status]}</span> ${esc(c.text)}${c.reply ? `<div class="reply">${esc(c.reply)}</div>` : ''}</li>`).join('')}</ul>
    </section>
    ${r ? `<section><h3>נתוני סריקה</h3><div class="kv small" dir="ltr">
      status ${esc(r.status)} · TV R:R ${fmt(r.tv_rr)} · zone dist ${fmt(r.tv_zone_dist_atr, 1)} ATR · wATR ${fmt(r.weekly_atr)}<br/>
      earnings ${r.days_to_earnings ?? '?'}d ${r.tv_stale ? `· stale: ${esc(r.tv_stale)}` : ''}<br/>
      ${r.badges.includes('hammer') ? `${esc(r.last_week_reversal_kind)} E ${fmt(r.hammer_entry)} SL ${fmt(r.hammer_sl)} TP ${fmt(r.hammer_tp)} R:R ${fmt(r.hammer_rr)} calm ${r.hammer_calm_weeks ?? '?'}w` : ''}
      ${r.tradingview_url ? `<br/><a href="${esc(r.tradingview_url)}" target="_blank" rel="noopener">TradingView ↗</a>` : ''}</div></section>` : ''}
    <div class="spacer"></div>`;

  p.querySelectorAll<HTMLElement>('.card[data-id]').forEach((c) => {
    const id = c.dataset.id!;
    $('.selbtn', c)?.addEventListener('click', () => { S.selected = S.selected === id ? null : id; syncChart(); renderPanel(); });
    c.querySelectorAll<HTMLInputElement>('input[data-f]').forEach((i) => {
      i.addEventListener('input', () => {
        const d = S.drawings.get(id); if (!d) return;
        const f = i.dataset.f!; (d as any)[f] = i.type === 'date' ? (i.value || null) : (i.value === '' ? null : +i.value);
        syncChart(); const rrEl = $('.rr', c); if (rrEl) rrEl.textContent = rrText(d);
      });
      i.addEventListener('change', async () => {
        const d = S.drawings.get(id); if (!d) return;
        const f = i.dataset.f as keyof Drawing;
        await guard(api.updateDrawing(id, { [f]: d[f] } as Partial<Drawing>), 'נשמר');
      });
      i.addEventListener('blur', () => setTimeout(() => { if (panelDirty) renderPanel(); }, 0));
    });
    c.querySelectorAll<HTMLButtonElement>('.act').forEach((b) => (b.onclick = async () => {
      const a = b.dataset.act!;
      if (a === 'delete') {
        if (!confirm('למחוק את השרטוט?')) return;
        S.drawings.delete(id); if (S.selected === id) S.selected = null; syncChart(); renderPanel();
        await guard(api.deleteDrawing(id), 'נמחק');
      } else {
        const status = a === 'approve' ? 'approved' : a === 'reject' ? 'rejected' : 'review';
        const d = S.drawings.get(id); if (d) d.status = status; syncChart(); renderPanel();
        await guard(api.updateDrawing(id, { status }), status === 'approved' ? 'אושר' : status === 'rejected' ? 'נדחה' : 'הוחזר');
      }
    }));
  });
  p.querySelectorAll<HTMLButtonElement>('.lab').forEach((b) => (b.onclick = async () => {
    const l: Label = { ticker: t, label: 'technical', value: b.dataset.v!, note: null, asof: today(), created_at: new Date().toISOString() };
    S.labels = S.labels.filter((x) => !(x.ticker === t && x.label === 'technical' && x.asof === l.asof)); S.labels.push(l); renderPanel();
    await guard(api.upsertLabel(l), 'נשמר');
  }));
  const niW = $('#niWeeks') as HTMLSelectElement | null;
  if (niW) niW.onchange = () => { S.ui.niWeeks = +niW.value; saveUi(); };
  const niOnB = $('#niOn'); if (niOnB) niOnB.onclick = () => setNi(t, niW && +niW.value ? +niW.value : null, true);
  const niOffB = $('#niOff'); if (niOffB) niOffB.onclick = () => setNi(t, null, false);
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

// ---------------- realtime ----------------
function onChange(table: Table, ev: string, row: any, old: any) {
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
  if (cv && S.ticker) { renderHeader(); syncChart(); renderPanel(); }
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
}

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
}

api.onAuth((e) => { if (e !== S.email || (e && !S.loaded)) onLogin(e); });
api.session().then((s) => onLogin(s.email));

if ('serviceWorker' in navigator && import.meta.env.PROD && !api.demo) {
  navigator.serviceWorker.register(import.meta.env.BASE_URL + 'sw.js').catch(() => {});
}
// expose for tests / debugging
(window as any).__srs = { S, api, atr };
