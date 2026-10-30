// Stock lists for the side list (Eyal 2026-10-30: "the list on the right can be a static list of stocks or a dynamic
// search result from predefined criteria; switch between lists"). Pure helpers; main.ts resolves the rows.
//  - built-in lists (not editable): all stocks, PASS, ★ starred (= the watchlist table), open positions
//  - his own lists (Supabase table stock_lists, owner-only RLS; localStorage copy as offline fallback):
//    static = tickers he adds, dynamic = a saved filter set (the app's own filters.ts criteria)
import { isActive, type Filters } from './filters';

export type ListKind = 'static' | 'dynamic';
export interface StockList {
  id: string;
  name: string;
  kind: ListKind;
  tickers: string[];
  criteria: { f: Filters } | null;
  pos: number;
  builtin?: boolean;
  created_at?: string;
  updated_at?: string;
}

export const BUILTIN_LISTS: StockList[] = [
  { id: 'all', name: 'כל המניות', kind: 'dynamic', tickers: [], criteria: { f: {} }, pos: -4, builtin: true },
  { id: 'pass', name: 'PASS', kind: 'dynamic', tickers: [], criteria: { f: { st_pass: { on: true } } }, pos: -3, builtin: true },
  // the old ★ chip listed starred tickers even when marked unfit
  { id: 'starred', name: '★ מעקב', kind: 'dynamic', tickers: [], criteria: { f: { starred: { on: true }, unfit: { on: true, mode: 'all' } } }, pos: -2, builtin: true },
  { id: 'positions', name: 'פוזיציות', kind: 'dynamic', tickers: [], criteria: { f: { position: { on: true }, unfit: { on: true, mode: 'all' } } }, pos: -1, builtin: true },
];
export const LISTS_LS = 'srs-lists-v1';

/** "aapl, msft nvda\nNYSE:KNX" -> ['AAPL', 'MSFT', 'NVDA', 'KNX'] (exchange prefix dropped, unique, order kept) */
export function parseTickers(s: string): string[] {
  const out: string[] = [];
  for (const raw of String(s || '').split(/[\s,;]+/)) {
    const t = raw.trim().toUpperCase().replace(/^[A-Z]+:/, '').replace(/[^A-Z0-9.\-]/g, '');
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

/** Filters that decide the rows of a list together with the panel's own filters: the panel's active filters are ANDed
 *  on top (same id -> the panel wins). Static lists show every ticker in them, also ones marked unfit. */
export function effectiveFilters(list: StockList, panel: Filters): Filters {
  const base: Filters = list.kind === 'static' ? { unfit: { on: true, mode: 'all' } } : { ...(list.criteria?.f || {}) };
  for (const [id, s] of Object.entries(panel || {})) if (isActive(id, s)) base[id] = s;
  return base;
}

export const sortLists = (ls: StockList[]) => [...ls].sort((a, b) => a.pos - b.pos || String(a.created_at || '').localeCompare(String(b.created_at || '')) || a.name.localeCompare(b.name));

/** local copy (offline / Supabase table missing) */
export function loadLocalLists(store: Pick<Storage, 'getItem'> | null = typeof localStorage !== 'undefined' ? localStorage : null): StockList[] {
  try { const v = JSON.parse(store?.getItem(LISTS_LS) || '[]'); return Array.isArray(v) ? v.filter((x) => x && x.id && x.name) : []; } catch { return []; }
}
export function saveLocalLists(ls: StockList[], store: Pick<Storage, 'setItem'> | null = typeof localStorage !== 'undefined' ? localStorage : null) {
  try { store?.setItem(LISTS_LS, JSON.stringify(ls.filter((l) => !l.builtin))); } catch { /* full */ }
}
