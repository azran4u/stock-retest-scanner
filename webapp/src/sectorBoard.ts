// Sector board on #/stages (T-7, Eyal 2026-11-26): SPDR sector strip, top-10 daily mini charts
// (lightweight-charts), recommendations, large daily chart, and stage filters.
// Badge 2a = above the 150-day / 30-week SMA and still at or below resistance (pre-breakout).
// Distinct from pipeline sub-stage 2A (fresh stage-2 breakout), which is shown as badge 2.
import type { Bar } from './types';
import { fetchData } from './data';

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const f = (n: number | null | undefined, d = 2) => n == null || Number.isNaN(+n) ? '—' : (+n).toFixed(d);

export type BoardBadge = '1' | '2a' | '2' | '3' | '4' | string;
export interface BoardRec {
  kind: string; he: string; entry: number | null; stop: number | null; side: string | null;
  res: number | null; sup: number | null; bo_lvl: number | null; bd_lvl: number | null;
}
export interface BoardFlags { near_res: boolean; near_sup: boolean; retest2: boolean; retest4: boolean }
export interface BoardStock {
  t: string; n: string | null; sec: string | null; etf: string | null; mcap_b: number | null;
  stage: number; sub: string | null; badge: BoardBadge; close: number; ma30: number | null; atr_w: number | null;
  res: number | null; sup: number | null; bo_lvl: number | null; bd_lvl: number | null;
  flags: BoardFlags; rec: BoardRec; hist_start: string | null; hist_days: number | null;
}
export interface BoardSector {
  etf: string; name: string; name_en: string; stage: number; sub: string | null; badge: BoardBadge;
  close: number | null; ma30: number | null; atr_w: number | null; res: number | null; sup: number | null;
  rs: number | null; stocks: string[];
}
export interface BoardDoc {
  version: number; generated_at: string; week: string | null; source: string; badge_2a: string;
  near_pct?: number; near_atrs?: number; near?: string; daily_years: number; daily_path: string; top_n: number;
  sectors: BoardSector[]; stocks: Record<string, BoardStock>;
  filters: { '2a_res': string[]; '3_sup': string[]; retest2: string[]; retest4: string[] };
  hist_min_start?: string | null;
}

export type BoardFilter = '2a_res' | '3_sup' | 'retest2' | 'retest4';
export const BOARD_FILTERS: [BoardFilter, string][] = [
  ['2a_res', '2a ליד התנגדות'],
  ['3_sup', '3 ליד תמיכה'],
  ['retest2', '2 ריטסט (לונג)'],
  ['retest4', '4 ריטסט (שורט)'],
];

export interface StagesRoute {
  mode: 'list' | 'stock' | 'board';
  t: string | null;
  sec: string | null;
  f: BoardFilter | null;
}

export function parseStagesHash(hash = location.hash): StagesRoute {
  const raw = hash.slice(1);
  const qIdx = raw.indexOf('?');
  const path = qIdx >= 0 ? raw.slice(0, qIdx) : raw;
  const q = new URLSearchParams(qIdx >= 0 ? raw.slice(qIdx + 1) : '');
  const parts = path.split('/').filter(Boolean);
  const fRaw = q.get('f');
  const f = (BOARD_FILTERS.some(([k]) => k === fRaw) ? fRaw : null) as BoardFilter | null;
  if (parts[0] !== 'stages') return { mode: 'list', t: null, sec: null, f };
  if (parts[1] === 'board') {
    const secRaw = parts[2] && parts[2] !== '_' ? decodeURIComponent(parts[2]).toUpperCase() : (q.get('sec') || '');
    const t = parts[3] ? decodeURIComponent(parts[3]).toUpperCase() : (q.get('t') ? q.get('t')!.toUpperCase() : null);
    return { mode: 'board', t, sec: secRaw || null, f };
  }
  const t = parts[1] ? decodeURIComponent(parts[1]).toUpperCase() : null;
  return { mode: t ? 'stock' : 'list', t, sec: null, f };
}

export function boardHref(sec: string | null, t?: string | null, f?: string | null): string {
  let h = '#/stages/board';
  if (sec) h += '/' + encodeURIComponent(sec);
  else if (t || f) h += '/_';
  if (t) h += '/' + encodeURIComponent(t);
  if (f) h += '?f=' + encodeURIComponent(f);
  return h;
}

const ICONS: Record<string, string> = {
  XLK: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="9" width="16" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 9V7a4 4 0 0 1 8 0v2" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="9.5" cy="14" r="1" fill="currentColor"/><circle cx="14.5" cy="14" r="1" fill="currentColor"/></svg>',
  XLF: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 18h16M6 18V10l6-5 6 5v8M10 18v-4h4v4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
  XLV: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M6 10h12" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  XLE: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 3 6 13h6l-1 8 8-12h-6l0-6z" fill="currentColor"/></svg>',
  XLI: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M6.2 6.2l2.1 2.1M15.7 15.7l2.1 2.1M17.8 6.2l-2.1 2.1M8.3 15.7 6.2 17.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
  XLY: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8h14l-1.2 11H6.2L5 8z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 8V7a4 4 0 0 1 8 0v1" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
  XLP: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9h12l-1 11H7L6 9zM9 9V7h6v2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M10 13h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  XLU: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7V4h6v3M8 20h8M12 7v9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M8 16h8v2a4 4 0 0 1-8 0v-2z" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
  XLB: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16 12 8l8 8H4z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M7 16v3h10v-3" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
  XLRE: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V10l8-6 8 6v10H4z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M10 20v-6h4v6" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
  XLC: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 16a7 7 0 0 1 14 0M8 16a4 4 0 0 1 8 0" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="12" cy="18" r="1.4" fill="currentColor"/></svg>',
};

export function badgeHtml(badge: BoardBadge, extra = ''): string {
  const cls = badge === '2a' ? 'st2a' : /^[1-4]$/.test(badge) ? `st${badge}` : 'st0';
  return `<span class="stbadge ${cls}${extra ? ' ' + extra : ''}">${esc(badge)}</span>`;
}

export function sectorStripHtml(board: BoardDoc, route: StagesRoute): string {
  const tiles = board.sectors.map((s) => {
    const on = route.sec === s.etf ? ' on' : '';
    const href = route.sec === s.etf && !route.f ? '#/stages' : boardHref(s.etf, null, route.f);
    return `<a class="stsec stsec-${s.badge}${on}" href="${href}" data-sec="${esc(s.etf)}" title="${esc(s.name_en)} · שלב ${esc(s.badge)}">
      <span class="stsec-ic">${ICONS[s.etf] || ICONS.XLI}</span>
      <span class="stsec-name">${esc(s.name)}</span>
      <span class="stsec-etf" dir="ltr">${esc(s.etf)}</span>
      ${badgeHtml(s.badge, 'stsec-bd')}
    </a>`;
  }).join('');
  const filters = BOARD_FILTERS.map(([k, he]) => {
    const n = board.filters[k]?.length ?? 0;
    const on = route.f === k ? ' on' : '';
    const href = route.f === k ? boardHref(route.sec) : boardHref(route.sec, null, k);
    return `<a class="chip${on}" href="${href}" data-bf="${k}">${he} <span class="cnt">${n}</span></a>`;
  }).join('');
  const src = 'סקטורים לפי תעודות SPDR (XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLB, XLRE, XLC). 2a = מעל ממוצע 150 יום, לפני פריצה. ״קרוב״ בסינון = עד ATR שבועי אחד.';
  return `<section class="stsectors" aria-label="סקטורים">
    <div class="stsec-row">${tiles}</div>
    <div class="chips stboard-filters" role="tablist" aria-label="סינון לוח סקטורים">${filters}</div>
    <div class="stsec-note small muted">${src}</div>
  </section>`;
}

export function boardStocks(board: BoardDoc, route: StagesRoute): BoardStock[] {
  let ids: string[] = [];
  if (route.f && board.filters[route.f]) ids = board.filters[route.f].slice();
  else if (route.sec) {
    const s = board.sectors.find((x) => x.etf === route.sec);
    ids = s?.stocks?.slice() ?? [];
  }
  if (route.f && route.sec) {
    const allow = new Set(board.sectors.find((x) => x.etf === route.sec)?.stocks ?? []);
    // Filter is universe-wide; when a sector is also selected, intersect with that sector's full membership via etf field
    ids = board.filters[route.f].filter((t) => {
      const st = board.stocks[t];
      return st && (st.etf === route.sec || allow.has(t));
    });
    // also include filter hits in this sector even if not in the top 10
    const extra = board.filters[route.f].filter((t) => board.stocks[t]?.etf === route.sec && !ids.includes(t));
    ids = [...ids, ...extra];
  }
  return ids.map((t) => board.stocks[t]).filter((x): x is BoardStock => !!x);
}

export function minisHtml(board: BoardDoc, route: StagesRoute, stocks: BoardStock[]): string {
  const sec = route.sec ? board.sectors.find((s) => s.etf === route.sec) : null;
  const fHe = route.f ? (BOARD_FILTERS.find(([k]) => k === route.f)?.[1] ?? route.f) : null;
  const title = sec && fHe ? `${sec.name} · ${fHe}` : sec ? `10 הגדולות ב${sec.name} (${sec.etf})` : fHe ? fHe : 'לוח סקטורים';
  const back = `<a class="ghost btnlike small stboard-back" href="#/stages">← הרשימה</a>`;
  if (!stocks.length) {
    return `<div class="stminis-wrap" id="stMinis"><div class="stminis-head">${back}<h3>${esc(title)}</h3></div>
      <div class="center muted">אין מניות שתואמות את הסינון</div></div>`;
  }
  const cards = stocks.map((s) => `<article class="stmini" data-stmini="${esc(s.t)}">
    <header class="stmini-hd">
      <div class="stmini-tk"><b dir="ltr">${esc(s.t)}</b> ${badgeHtml(s.badge)}
        <span class="muted small" dir="ltr">$${f(s.close)}</span>
        ${s.mcap_b != null ? `<span class="muted small" dir="ltr">${f(s.mcap_b, 0)}B</span>` : ''}</div>
      <div class="small muted stmini-nm">${esc(s.n || '')}${s.etf ? ` · <span dir="ltr">${esc(s.etf)}</span>` : ''}</div>
    </header>
    <div class="stmini-chart" data-stmini-chart="${esc(s.t)}"><button type="button" class="stmini-hit" data-stmini-open="${esc(s.t)}" aria-label="פתח גרף גדול של ${esc(s.t)}"></button></div>
    <p class="stmini-rec small">${esc(s.rec.he)}</p>
  </article>`).join('');
  return `<div class="stminis-wrap" id="stMinis">
    <div class="stminis-head">${back}<h3>${esc(title)} <span class="cnt">${stocks.length}</span></h3>
      <span class="small muted">גרף יומי · תמיכה / התנגדות / ממוצע 150 יום · ATR שבועי. לחיצה על הגרף פותחת גרף גדול. המלצות בלבד, בלי פקודות.</span>
    </div>
    <div class="stminis">${cards}</div>
  </div>`;
}

export function largeChartHtml(s: BoardStock, route: StagesRoute): string {
  const backHref = boardHref(route.sec, null, route.f);
  return `<div class="stbig-daily" id="stBigDaily">
    <header class="stbig-hd">
      <a class="ghost btnlike small" href="${backHref}" id="stBoardBack">← לגרפים המוקטנים</a>
      <div class="tk"><b dir="ltr">${esc(s.t)}</b> ${badgeHtml(s.badge)} <span class="muted small" dir="ltr">$${f(s.close)}</span>
        <div class="small muted stname">${esc(s.n || '')}${s.etf ? ` · <span dir="ltr">${esc(s.etf)}</span>` : ''}${s.mcap_b != null ? ` · שווי ${f(s.mcap_b, 1)}B` : ''}</div>
      </div>
    </header>
    <div class="stbig stbig-d" id="stbigd" role="img" aria-label="גרף יומי ${esc(s.t)}"></div>
    <p class="stnodata muted" id="stnodata-d" hidden>אין נתונים יומיים ל-${esc(s.t)}</p>
    <p class="stmini-rec">${esc(s.rec.he)}</p>
    <p class="small muted">כתום = ממוצע 150 יום · כחול = התנגדות · אדום = תמיכה · ATR(W) בפינה. גרף יומי, עד ${s.hist_start ? 'תחילת הנתונים ' + s.hist_start : '10 שנים'}. המלצה בלבד — לא מציבה פקודות.</p>
  </div>`;
}

export function smaPoints(bars: Bar[], n: number): { time: string; value: number }[] {
  const out: { time: string; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= n) sum -= bars[i - n].close;
    if (i >= n - 1) out.push({ time: bars[i].time, value: sum / n });
  }
  return out;
}

const dailyCache = new Map<string, Promise<Bar[]>>();
export function loadBoardDaily(t: string): Promise<Bar[]> {
  if (!dailyCache.has(t)) {
    dailyCache.set(t, fetchData('sector_daily/' + encodeURIComponent(t) + '.json').then(async (r) => {
      if (!r.ok) return [];
      const j = await r.json() as { d?: [string, number, number, number, number, number][] };
      return (j.d || []).map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
    }).catch(() => []));
  }
  return dailyCache.get(t)!;
}

export function srDrawings(t: string, res: number | null | undefined, sup: number | null | undefined) {
  const ln = (id: string, p: number, color: string) => ({
    id, ticker: t, kind: 'line' as const, entry: p, stop: null, target: null, zone_top: null, zone_bottom: null,
    t_start: null, t_end: null, source: 'bot' as const, status: 'active' as const, note: null,
    meta: { nolabel: true, color, dash: '' },
  });
  const out = [];
  if (res != null) out.push(ln('b-res', res, '#2962ff'));
  if (sup != null) out.push(ln('b-sup', sup, '#ef5350'));
  return out;
}
