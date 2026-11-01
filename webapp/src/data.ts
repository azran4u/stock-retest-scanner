import type { Bar, Row, TvDrawing } from './types';

const BASE = import.meta.env.BASE_URL + 'data/';
/** Where the data files come from (Eyal 2026-10-30, private data): the logged-in app reads the private Supabase Storage
 *  bucket 'app-data' (api.ts dataFetch, owner-only policy); demo mode / tests read the local build's data/ folder. */
export type DataFetcher = (path: string) => Promise<Response>;
let fetcher: DataFetcher = (path) => fetch(BASE + path, { cache: 'no-cache' });
export function setDataFetcher(f: DataFetcher) { fetcher = f; }
export const fetchData = (path: string) => fetcher(path);
const candleCache = new Map<string, Promise<Bar[]>>();

export async function loadIndex(): Promise<{ rows: Row[]; report_date: string | null; generated_at: string }> {
  const r = await fetcher('index.json');
  if (!r.ok) throw new Error('index.json ' + r.status);
  return r.json();
}

export async function loadTv(): Promise<Record<string, TvDrawing>> {
  const r = await fetcher('tv_drawings.json');
  return r.ok ? r.json() : {};
}

/** List mini charts: last ~156 weekly OHLC candles per ticker (export_data.spark_series).
 *  q = base64 of n*4 bytes (o,h,l,c per week), each quantized 0..255 between lo and hi. */
export interface Spark { w0: string; lo: number; hi: number; n: number; q: string; ma?: { lo: number; hi: number; q: string } }
export interface SparkBars { lo: number; hi: number; o: number[]; h: number[]; l: number[]; c: number[] }
export function decodeSpark(sp: Spark): SparkBars {
  const b = atob(sp.q), k = (sp.hi - sp.lo) / 255;
  const o: number[] = [], h: number[] = [], l: number[] = [], c: number[] = [];
  for (let i = 0; i + 3 < b.length; i += 4) {
    o.push(sp.lo + b.charCodeAt(i) * k); h.push(sp.lo + b.charCodeAt(i + 1) * k);
    l.push(sp.lo + b.charCodeAt(i + 2) * k); c.push(sp.lo + b.charCodeAt(i + 3) * k);
  }
  return { lo: sp.lo, hi: sp.hi, o, h, l, c };
}
/** Reversal candles per ticker for the 'reversal candle touching the level' filters (export -> revc.json, Eyal 2026-10-31):
 *  d = daily (last 60 completed sessions), w = weekly (last 26 completed weeks); [k, mask, low, close, atr]. */
let revcP: Promise<Record<string, { d: [number, number, number, number, number][]; w: [number, number, number, number, number][] }>> | null = null;
export function loadRevc() {
  revcP ??= fetcher('revc.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return revcP;
}
let sparkP: Promise<Record<string, Spark>> | null = null;
export function loadSpark(): Promise<Record<string, Spark>> {
  sparkP ??= fetcher('spark.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return sparkP;
}

/** Past + next earnings report dates per ticker (export_data -> srs_app/earnings_marks.py; Eyal 2026-10-28 chart 'E' markers).
 *  p = past reports oldest first: d date, t 'bmo' | 'amc' | null, e EPS estimate, a reported EPS, s surprise % (null = unknown).
 *  n = next report date (ne = estimated), nt / nest = its timing / EPS estimate when Yahoo has them. Funds are absent. */
export interface EarnPast { d: string; t: 'bmo' | 'amc' | null; e: number | null; a: number | null; s: number | null }
export interface EarnMarks { p: EarnPast[]; n: string | null; ne?: boolean; nt?: 'bmo' | 'amc' | null; nest?: number | null; src?: string }
let earnP: Promise<Record<string, EarnMarks>> | null = null;
export function loadEarnings(): Promise<Record<string, EarnMarks>> {
  earnP ??= fetcher('earnings.json').then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return earnP;
}

export function loadDaily(t: string): Promise<Bar[]> {
  let p = candleCache.get(t);
  if (!p) {
    p = fetcher('candles/' + encodeURIComponent(t) + '.json')
      .then((r) => { if (!r.ok) throw new Error('no candles for ' + t); return r.json(); })
      .then((j: { d: [string, number, number, number, number, number][] }) =>
        j.d.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume })));
    p.catch(() => candleCache.delete(t));
    candleCache.set(t, p);
  }
  return p;
}

/** Monday (UTC) of the week containing YYYY-MM-DD. */
export function weekStart(d: string): string {
  const dt = new Date(d + 'T00:00:00Z');
  const wd = (dt.getUTCDay() + 6) % 7; // Mon=0
  dt.setUTCDate(dt.getUTCDate() - wd);
  return dt.toISOString().slice(0, 10);
}

/** Daily -> weekly (Mon-Fri weeks, bar time = Monday, as TradingView). */
export function toWeekly(daily: Bar[]): Bar[] {
  const out: Bar[] = [];
  let cur: Bar | null = null;
  for (const b of daily) {
    const w = weekStart(b.time);
    if (!cur || cur.time !== w) {
      cur = { time: w, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume };
      out.push(cur);
    } else {
      cur.high = Math.max(cur.high, b.high);
      cur.low = Math.min(cur.low, b.low);
      cur.close = b.close;
      cur.volume += b.volume;
    }
  }
  return out;
}

/** Wilder ATR(14) of the last bar. */
export function atr(bars: Bar[], n = 14): number | null {
  if (bars.length < n + 1) return null;
  let a = 0;
  for (let i = 1; i < bars.length; i++) {
    const tr = Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - bars[i - 1].close), Math.abs(bars[i].low - bars[i - 1].close));
    a = i <= n ? a + tr / n : (a * (n - 1) + tr) / n;
  }
  return a;
}

export function rr(entry: number | null | undefined, stop: number | null | undefined, target: number | null | undefined): number | null {
  if (entry == null || stop == null || target == null) return null;
  const risk = entry - stop;
  if (risk <= 0) return null;
  return (target - entry) / risk;
}

/** Expert zone per starred ticker (Eyal 2026-11-01, srs_app/expert_zone.py -> expert_zones.json): the base top of the last
 *  breakout (wick -> body) + a 0-100 significance score with its factors. A separate overlay only: never a drawing,
 *  never part of PASS / sizing / R:R / filters. */
export interface ExpertFactor { k: string; he: string; pts: number; max: number; val: string; src: string }
export interface ExpertZone {
  ok: boolean; reason?: string; top?: number; bottom?: number; atr_w?: number; base_start?: string; pivot_week?: string;
  breakout_week?: string; breakout_close?: number; post_high?: number; price?: number; dist_atr?: number;
  hammers?: { w: string; s: 'H' | 'h'; k: number }[]; closes_below_k?: number[]; last_week?: string;
  origin?: { top: number; bottom: number; base_start: string }; shelf?: { lows: [string, number][]; src: string } | null;
  width_note?: string | null; score?: number; factors?: ExpertFactor[];
  /** single weekly close under the zone bottom since the breakout (not followed by a second): valid, flagged, -10 pts */
  warnings?: { k: string; date: string; he: string }[];
  /** expert Entry / SL / TP (srs_app/expert_zone._trade): separate overlay, never a Long / PASS / sizing input */
  trade?: { entry: number; sl: number; tp: number; rr: number | null; tp_mm: number; retest_low: number; risk_pct: number; confirmed: boolean; notes: string[] } | null;
}
export interface ExpertDoc { rule_version: string; generated_at: string; labels?: Record<string, string>; sources?: Record<string, string>; tickers: Record<string, ExpertZone> }
let expertP: Promise<ExpertDoc | null> | null = null;
export function loadExpert(): Promise<ExpertDoc | null> {
  // factor labels / sources are stored once per file (doc.labels / doc.sources) -> filled back into every factor
  expertP ??= fetcher('expert_zones.json').then((r) => (r.ok ? r.json() : null)).then((d: ExpertDoc | null) => {
    if (d) for (const z of Object.values(d.tickers || {})) for (const f of z.factors || []) { f.he ??= d.labels?.[f.k] ?? f.k; f.src ??= d.sources?.[f.k] ?? ''; }
    return d;
  }).catch(() => null);
  return expertP;
}
