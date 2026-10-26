// Independent list filters combined with logical AND (Eyal 2026-10-26: "every filter stands on its own; turning on
// several = logical AND"). Pure: main.ts builds a Facts object per row (export values + live app values: R:R, zone
// distance, PASS/WAIT, drawings, labels, positions, sizing) and `matches` checks every active filter.

export const REV_KINDS = ['hammer', 'engulfing', 'strong_close', 'rejection'] as const;
export type RevKind = typeof REV_KINDS[number];
export const REV_HE: Record<RevKind, string> = { hammer: 'פטיש', engulfing: 'בולע', strong_close: 'סגירה חזקה', rejection: 'דחייה (פתיל תחתון)' };

export interface Facts {
  technical: boolean | null;
  rr: number | null;
  revD: Partial<Record<RevKind, string>>;   // kind -> date of the most recent daily candle of that shape
  revW: Partial<Record<RevKind, string>>;   // kind -> date (week end) of the most recent weekly candle
  daysToEarn: number | null;                // null = unknown date
  earnNone?: boolean;                       // no earnings in any source (ETFs...) -> passes 'days to earnings'
  unfit: boolean;
  status: string;                           // live PASS / FAIL / OUT ... (WAIT cancelled 2026-10-26)
  needsDrawing: boolean; review: boolean; obsolete: boolean; hammer: boolean; position: boolean;
  starred: boolean; mine: boolean; commands: boolean;
  zoneDist: number | null;                  // weekly ATRs from the live zone (0 inside); null = no zone
  dollarVol: number | null;                 // 30d avg $ volume
  history: boolean | null; tradable: boolean | null; fromAbove: boolean | null;
  noInvHammer: boolean | null; noRedVol: boolean | null;
  smoothWeeks: number | null;
  sector: string | null;
  instOwn: number | null; shortFloat: number | null;   // % ; null = no data (never filtered out)
  fib: boolean;                             // price near a key Fib level or the zone coincides with one
  today: string;                            // YYYY-MM-DD (Israel) for "within X weeks"
}

export type UnfitMode = 'hide' | 'only' | 'all';
export interface FState { on: boolean; x?: number; kinds?: RevKind[]; v?: string; mode?: UnfitMode }
export type Filters = Record<string, FState>;

export interface FilterDef {
  id: string; label: string; group: 'main' | 'status' | 'setup';
  /** numeric parameter: shown as a small input next to the toggle */
  param?: { def: number; min: number; max: number; step: number; unit?: string; pre?: string };
  kinds?: boolean;      // reversal kinds picker
  select?: 'sector';
  tri?: boolean;        // unfit: hide / only / all
  test: (f: Facts, s: FState) => boolean;
}

const minusDays = (iso: string, n: number) => { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() - n); return d.toISOString().slice(0, 10); };
export function withinWeeks(m: Partial<Record<RevKind, string>>, kinds: readonly RevKind[], weeks: number, today: string): boolean {
  const from = minusDays(today, Math.round(7 * weeks));
  return kinds.some((k) => { const d = m[k]; return !!d && d >= from; });
}
const t = (b: boolean | null) => b === true;

export const FILTERS: FilterDef[] = [
  // ---- main (Eyal's list) ----
  { id: 'uptrend', label: 'מגמת עליה ראשית', group: 'main', test: (f) => t(f.technical) },
  { id: 'rr', label: 'R:R ≥', group: 'main', param: { def: 2, min: 0, max: 20, step: 0.1 }, test: (f, s) => f.rr != null && f.rr >= (s.x ?? 2) },
  { id: 'revD', label: 'נר היפוך יומי ב-', group: 'main', param: { def: 1, min: 1, max: 26, step: 1, unit: 'שבועות אחרונים' }, kinds: true,
    test: (f, s) => withinWeeks(f.revD, s.kinds?.length ? s.kinds : DEF_KINDS, s.x ?? 1, f.today) },
  { id: 'revW', label: 'נר היפוך שבועי ב-', group: 'main', param: { def: 2, min: 1, max: 26, step: 1, unit: 'שבועות אחרונים' }, kinds: true,
    test: (f, s) => withinWeeks(f.revW, s.kinds?.length ? s.kinds : DEF_KINDS, s.x ?? 2, f.today) },
  { id: 'earn', label: 'ימים עד דוחות ≥', group: 'main', param: { def: 14, min: 0, max: 120, step: 1 }, test: (f, s) => !!f.earnNone || (f.daysToEarn != null && f.daysToEarn >= (s.x ?? 14)) },
  { id: 'unfit', label: 'לא מתאימות לשיטה', group: 'main', tri: true,
    test: (f, s) => ((s.mode ?? 'hide') === 'all' ? true : (s.mode ?? 'hide') === 'only' ? f.unfit : !f.unfit) },
  // ---- status / app ----
  { id: 'st_pass', label: 'PASS', group: 'status', test: (f) => f.status === 'PASS' },
  { id: 'st_review', label: 'לבדיקה', group: 'status', test: (f) => f.review },
  { id: 'st_obsolete', label: 'שרטוט לא עדכני', group: 'status', test: (f) => f.obsolete },
  { id: 'hammer', label: 'פטיש שבוע אחרון', group: 'status', test: (f) => f.hammer },
  { id: 'position', label: 'פוזיציה פתוחה', group: 'status', test: (f) => f.position },
  { id: 'starred', label: '★ מעקב', group: 'status', test: (f) => f.starred },
  { id: 'mine', label: 'יש לי שרטוט', group: 'status', test: (f) => f.mine },
  { id: 'commands', label: 'פקודות לבוט', group: 'status', test: (f) => f.commands },
  // ---- setup / data ----
  { id: 'near', label: 'קרוב לאזור ≤', group: 'setup', param: { def: 1, min: 0, max: 10, step: 0.1, unit: 'ATR שבועי' }, test: (f, s) => f.zoneDist != null && f.zoneDist <= (s.x ?? 1) },
  { id: 'dvol', label: 'מחזור $ ≥', group: 'setup', param: { def: 50, min: 0, max: 100000, step: 10, unit: 'מיליון (ממוצע 30 יום)' }, test: (f, s) => f.dollarVol != null && f.dollarVol >= (s.x ?? 50) * 1e6 },
  { id: 'history', label: 'היסטוריה ≥ 3 שנים', group: 'setup', test: (f) => t(f.history) },
  { id: 'tradable', label: 'סחירה לחשבון (ATR שבועי < סיכון)', group: 'setup', test: (f) => t(f.tradable) },
  { id: 'fromAbove', label: 'חזרה לאזור מלמעלה', group: 'setup', test: (f) => t(f.fromAbove) },
  { id: 'noInvHammer', label: 'אין פטיש הפוך', group: 'setup', test: (f) => f.noInvHammer !== false },
  { id: 'noRedVol', label: 'אין שבוע אדום עם מחזור גבוה', group: 'setup', test: (f) => f.noRedVol !== false },
  { id: 'smooth', label: 'ירידה רגועה ≥', group: 'setup', param: { def: 5, min: 0, max: 104, step: 1, unit: 'שבועות' }, test: (f, s) => f.smoothWeeks != null && f.smoothWeeks >= (s.x ?? 5) },
  { id: 'fib', label: 'התלכדות פיבונאצי', group: 'setup', test: (f) => f.fib },
  { id: 'sector', label: 'תחום', group: 'setup', select: 'sector', test: (f, s) => !s.v || f.sector === s.v },
  { id: 'inst', label: 'אחזקה מוסדית ≥', group: 'setup', param: { def: 60, min: 0, max: 100, step: 5, unit: '% (חסר = עובר)' }, test: (f, s) => f.instOwn == null || f.instOwn >= (s.x ?? 60) },
  { id: 'short', label: 'Short float ≤', group: 'setup', param: { def: 5, min: 0, max: 100, step: 0.5, unit: '% (חסר = עובר)' }, test: (f, s) => f.shortFloat == null || f.shortFloat <= (s.x ?? 5) },
];
export const DEF_KINDS: RevKind[] = ['hammer', 'engulfing'];
export const BY_ID = new Map(FILTERS.map((d) => [d.id, d]));

/** a filter counts as active when it changes the default list (unfit: anything but 'hide') */
export function isActive(id: string, s: FState | undefined): boolean {
  if (id === 'unfit') return (s?.mode ?? 'hide') !== 'hide';
  if (id === 'sector') return !!s?.on && !!s.v;
  return !!s?.on;
}
export function activeCount(fs: Filters): number { return FILTERS.filter((d) => isActive(d.id, fs[d.id])).length; }

/** AND of every active filter; 'unfit' always applies (default hide). */
export function matches(f: Facts, fs: Filters): boolean {
  for (const d of FILTERS) {
    const s = fs[d.id];
    if (d.id === 'unfit') { if (!d.test(f, s || { on: true })) return false; continue; }
    if (!s?.on) continue;
    if (!d.test(f, s)) return false;
  }
  return true;
}
