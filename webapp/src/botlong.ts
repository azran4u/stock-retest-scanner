// Bot Long for a GIVEN zone — TS mirror of srs_app.bot_drawings.long_from_zone (Eyal 2026-10-23: when he moves a
// zone, a bot Long follows it; TP is not touched). Pure functions, no DOM: unit-checked against the Python rule by
// webapp/test_botlong.mjs on tests/golden/zone_long_golden.json.gz.
//   entry = zone top - 0.13 x weekly ATR(14)            (ATR = SMA of the true range, stock_screen.atr_series)
//   SL    = 0.1% under the lowest weekly low that gives risk 0.9-1.2 x weekly Wilder ATR(14), among the lows of the
//           current pullback (after the highest high of the last 26 weeks) and the lows of the last 52 weeks inside
//           [zone bottom - 0.75 ATR, zone top]; none fits -> entry - 1 Wilder ATR      (infer_v3d.sl_d, mode 'fit')
//   lows are spike-cleaned first (bot_drawings.despike_lows: isolated one-day spike wick -> min(open, close)).
import type { Bar } from './types';

export const ENTRY_BELOW_TOP = 0.13;
export const SL_PAD = 0.001;
export const SL_L = 52, SL_X = 0.75, SL_LO = 0.9, SL_HI = 1.2;
export const LOOKBACK_HI = 26;
export const SPIKE_K = 3.0;

export interface BotLong { entry: number; stop: number; sl_src: 'wick_low' | 'default_1atr'; atr: number; atr_w: number }

const r2 = (x: number) => Math.round(x * 100) / 100;

function median(a: number[]): number {
  const s = [...a].sort((x, y) => x - y), n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

/** bot_drawings.despike_lows: isolated one-day spike lows clipped to min(open, close). */
export function despike(daily: Bar[], k = SPIKE_K): Bar[] {
  const n = daily.length;
  if (n < 3) return daily;
  const tr = daily.map((b, i) => (i === 0 ? b.high - b.low
    : Math.max(b.high - b.low, Math.abs(b.high - daily[i - 1].close), Math.abs(b.low - daily[i - 1].close))));
  let out: Bar[] | null = null;
  for (let i = 1; i < n - 1; i++) {
    const win = tr.slice(Math.max(0, i - 20), i);
    if (win.length < 10) continue;
    const m = median(win);
    const b = daily[i], rng = b.high - b.low;
    if (!(rng > 0)) continue;
    const nb = Math.min(daily[i - 1].low, daily[i + 1].low);
    if (b.low < nb - k * m && (b.close - b.low) / rng >= 0.75 && (b.open - b.low) / rng >= 0.75) {
      out ??= daily.map((x) => ({ ...x }));
      out[i].low = Math.min(b.open, b.close);
    }
  }
  return out ?? daily;
}

/** Daily -> weekly (Mon-Fri), same buckets as pandas W-FRI on trading days. */
export function weeklyOf(daily: Bar[]): Bar[] {
  const out: Bar[] = [];
  let key = '';
  for (const b of daily) {
    const dt = new Date(b.time + 'T00:00:00Z');
    dt.setUTCDate(dt.getUTCDate() - ((dt.getUTCDay() + 6) % 7));
    const w = dt.toISOString().slice(0, 10);
    if (w !== key) { key = w; out.push({ ...b, time: w }); }
    else { const c = out[out.length - 1]; c.high = Math.max(c.high, b.high); c.low = Math.min(c.low, b.low); c.close = b.close; c.volume += b.volume; }
  }
  return out;
}

function trueRanges(w: Bar[]): number[] {
  return w.map((b, i) => (i === 0 ? b.high - b.low
    : Math.max(b.high - b.low, Math.abs(b.high - w[i - 1].close), Math.abs(b.low - w[i - 1].close))));
}

/** Entry / SL of the bot Long for zone [zb, zt] from daily candles (null when there is not enough history). */
export function botLongFromZone(daily: Bar[], zoneBottom: number, zoneTop: number): BotLong | null {
  const zb = Math.min(zoneBottom, zoneTop), zt = Math.max(zoneBottom, zoneTop);
  const w = weeklyOf(despike(daily));
  const n = w.length;
  if (n < Math.max(LOOKBACK_HI + 1, 15)) return null;
  const tr = trueRanges(w);
  const A = tr.slice(n - 14).reduce((s, x) => s + x, 0) / 14;          // SMA ATR(14)
  let Aw = tr[0];                                                       // Wilder: ewm(alpha=1/14, adjust=False)
  for (let i = 1; i < n; i++) Aw += (tr[i] - Aw) / 14;
  let ihi = n - LOOKBACK_HI;
  for (let i = n - LOOKBACK_HI; i < n; i++) if (w[i].high > w[ihi].high) ihi = i;
  const e = zt - ENTRY_BELOW_TOP * A;
  const js = new Set<number>();
  for (let j = ihi + 1; j < n; j++) js.add(j);
  for (let j = Math.max(0, n - SL_L); j < n; j++) if (zb - SL_X * A <= w[j].low && w[j].low <= zt) js.add(j);
  const cands = [...js].map((j) => w[j].low * (1 - SL_PAD)).filter((x) => x < e).sort((a, b) => a - b);
  const band = cands.filter((x) => SL_LO * Aw <= e - x && e - x <= SL_HI * Aw);
  const fromWick = band.length > 0;
  const sl = fromWick ? band[0] : e - 1.0 * Aw;
  return { entry: r2(e), stop: r2(sl), sl_src: fromWick ? 'wick_low' : 'default_1atr', atr: A, atr_w: Aw };
}
