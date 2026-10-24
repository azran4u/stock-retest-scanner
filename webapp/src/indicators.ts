// Daily SMAs + Fibonacci retracement anchor (Eyal 2026-10-24). Mirror of srs_app/fib.py; test_fib.mjs checks that both
// give the same anchor on every exported ticker. Informational only, NOT a PASS gate. Definitions: RULES.md §Fib.
import type { Bar } from './types';

export const SMA_PERIODS = [50, 100, 150, 200] as const;
export const SMA_COLORS: Record<number, string> = { 50: '#42a5f5', 100: '#e040fb', 150: '#ffb300', 200: '#eeeeee' };
export const ZZ_ATR_MULT = 3;
export const FIB_LEVELS = [0, 0.382, 0.5, 0.618, 1] as const;
export const FIB_KEY = [0.382, 0.5, 0.618] as const;
export const FIB_PRICE_TOL_ATR = 0.25;
export const FIB_ZONE_TOL_ATR = 0.1;
const ATR_N = 14;

const mondayOf = (d: string) => { const t = new Date(d.slice(0, 10) + 'T00:00:00Z'); t.setUTCDate(t.getUTCDate() - ((t.getUTCDay() + 6) % 7)); return t.toISOString().slice(0, 10); };

export interface WBar { time: string; open: number; high: number; low: number; close: number; lo_date: string; hi_date: string; last: string }
export function weeklyBars(daily: Bar[]): WBar[] {
  const out: WBar[] = [];
  for (const b of daily) {
    const w = mondayOf(b.time), cur = out[out.length - 1];
    if (!cur || cur.time !== w) { out.push({ time: w, open: b.open, high: b.high, low: b.low, close: b.close, lo_date: b.time, hi_date: b.time, last: b.time }); continue; }
    if (b.high > cur.high) { cur.high = b.high; cur.hi_date = b.time; }
    if (b.low < cur.low) { cur.low = b.low; cur.lo_date = b.time; }
    cur.close = b.close; cur.last = b.time;
  }
  return out;
}

export function wilderAtrSeries(bars: { high: number; low: number; close: number }[], n = ATR_N): (number | null)[] {
  const out: (number | null)[] = bars.map(() => null);
  let a = 0;
  for (let i = 1; i < bars.length; i++) {
    const tr = Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - bars[i - 1].close), Math.abs(bars[i].low - bars[i - 1].close));
    a = i <= n ? a + tr / n : (a * (n - 1) + tr) / n;
    if (i >= n) out[i] = a;
  }
  return out;
}

export interface Pivot { kind: 'H' | 'L'; i: number; price: number }
/** ZigZag on weekly bars: the leg flips when price moves >= mult x Wilder ATR(14) against the running extreme. */
export function zigzagPivots(bars: WBar[], mult = ZZ_ATR_MULT): Pivot[] {
  const atr = wilderAtrSeries(bars);
  const H = bars.map((b) => b.high), L = bars.map((b) => b.low);
  const argmax = (a: number, b: number) => { let k = a; for (let j = a + 1; j <= b; j++) if (H[j] > H[k]) k = j; return k; };
  const argmin = (a: number, b: number) => { let k = a; for (let j = a + 1; j <= b; j++) if (L[j] < L[k]) k = j; return k; };
  const piv: Pivot[] = [];
  let trend = 0, hi = 0, lo = 0, ext = 0;
  for (let i = 0; i < bars.length; i++) {
    const a = atr[i];
    if (trend === 0) {
      if (H[i] > H[hi]) hi = i;
      if (L[i] < L[lo]) lo = i;
      if (a == null) continue;
      const up = lo < i && H[i] - L[lo] >= mult * a, down = hi < i && H[hi] - L[i] >= mult * a;
      if (up && (!down || lo <= hi)) { piv.push({ kind: 'L', i: lo, price: L[lo] }); trend = 1; ext = argmax(lo + 1, i); }
      else if (down) { piv.push({ kind: 'H', i: hi, price: H[hi] }); trend = -1; ext = argmin(hi + 1, i); }
    } else if (trend === 1) {
      if (H[i] > H[ext]) ext = i;
      else if (a != null && H[ext] - L[i] >= mult * a) { piv.push({ kind: 'H', i: ext, price: H[ext] }); trend = -1; ext = argmin(ext + 1, i); }
    } else {
      if (L[i] < L[ext]) ext = i;
      else if (a != null && H[i] - L[ext] >= mult * a) { piv.push({ kind: 'L', i: ext, price: L[ext] }); trend = 1; ext = argmax(ext + 1, i); }
    }
  }
  return piv;
}

export interface Fib { low: number; low_date: string; high: number; high_date: string; atr_w: number | null }
/** Last confirmed swing low -> highest high after it (weekly). null = no confirmed low / nothing after it. */
export function fibAnchor(daily: Bar[], mult = ZZ_ATR_MULT): Fib | null {
  const bars = weeklyBars(daily);
  if (bars.length < ATR_N + 2) return null;
  const lows = zigzagPivots(bars, mult).filter((p) => p.kind === 'L');
  if (!lows.length) return null;
  const li = lows[lows.length - 1].i;
  if (li >= bars.length - 1) return null;
  let hi = li + 1;
  for (let j = li + 2; j < bars.length; j++) if (bars[j].high > bars[hi].high) hi = j;
  if (bars[hi].high <= bars[li].low) return null;
  const as = wilderAtrSeries(bars), a = as[as.length - 1] ?? null;
  return { low: bars[li].low, low_date: bars[li].lo_date, high: bars[hi].high, high_date: bars[hi].hi_date, atr_w: a };
}
export const fibPrice = (f: { low: number; high: number }, x: number) => f.high - x * (f.high - f.low);

export interface FibConf { priceLevel: number | null; zoneLevels: number[] }
export function fibConfluence(f: { low: number; high: number }, atrW: number | null | undefined, price?: number | null,
  zoneTop?: number | null, zoneBottom?: number | null): FibConf {
  const out: FibConf = { priceLevel: null, zoneLevels: [] };
  if (!atrW || atrW <= 0) return out;
  if (price != null) {
    let best: [number, number] | null = null;
    for (const x of FIB_KEY) { const d = Math.abs(price - fibPrice(f, x)); if (d <= FIB_PRICE_TOL_ATR * atrW && (!best || d < best[0])) best = [d, x]; }
    out.priceLevel = best ? best[1] : null;
  }
  if (zoneTop != null && zoneBottom != null) {
    const zt = Math.max(+zoneTop, +zoneBottom), zb = Math.min(+zoneTop, +zoneBottom), t = FIB_ZONE_TOL_ATR * atrW;
    out.zoneLevels = FIB_KEY.filter((x) => { const p = fibPrice(f, x); return p >= zb - t && p <= zt + t; });
  }
  return out;
}

/** Daily SMA(n) of closes: one value per daily bar (null until n closes). */
export function smaDaily(daily: Bar[], n: number): (number | null)[] {
  const out: (number | null)[] = []; let s = 0;
  for (let i = 0; i < daily.length; i++) {
    s += daily[i].close; if (i >= n) s -= daily[i - n].close;
    out.push(i >= n - 1 ? s / n : null);
  }
  return out;
}
/** Daily SMA sampled at each week's last trading day, keyed by the week's Monday (weekly bar time). */
export function smaWeekly(daily: Bar[], n: number): { time: string; value: number }[] {
  const sm = smaDaily(daily, n), out: { time: string; value: number }[] = [];
  for (let i = 0; i < daily.length; i++) {
    const last = i + 1 === daily.length || mondayOf(daily[i + 1].time) !== mondayOf(daily[i].time);
    if (last && sm[i] != null) out.push({ time: mondayOf(daily[i].time), value: sm[i]! });
  }
  return out;
}
