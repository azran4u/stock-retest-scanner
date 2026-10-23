import type { Bar, Row, TvDrawing } from './types';

const BASE = import.meta.env.BASE_URL + 'data/';
const candleCache = new Map<string, Promise<Bar[]>>();

export async function loadIndex(): Promise<{ rows: Row[]; report_date: string | null; generated_at: string }> {
  const r = await fetch(BASE + 'index.json', { cache: 'no-cache' });
  if (!r.ok) throw new Error('index.json ' + r.status);
  return r.json();
}

export async function loadTv(): Promise<Record<string, TvDrawing>> {
  const r = await fetch(BASE + 'tv_drawings.json', { cache: 'no-cache' });
  return r.ok ? r.json() : {};
}

/** List mini charts: last ~156 weekly OHLC candles per ticker (export_data.spark_series).
 *  q = base64 of n*4 bytes (o,h,l,c per week), each quantized 0..255 between lo and hi. */
export interface Spark { w0: string; lo: number; hi: number; n: number; q: string }
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
let sparkP: Promise<Record<string, Spark>> | null = null;
export function loadSpark(): Promise<Record<string, Spark>> {
  sparkP ??= fetch(BASE + 'spark.json', { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  return sparkP;
}

export function loadDaily(t: string): Promise<Bar[]> {
  let p = candleCache.get(t);
  if (!p) {
    p = fetch(BASE + 'candles/' + encodeURIComponent(t) + '.json')
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
