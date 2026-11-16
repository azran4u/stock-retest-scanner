// Confirmation candlestick patterns on the retest level (Eyal 2026-11-16, srs_app/confirm_patterns.py -> confirm.json).
// Evidence only: a confirmation of the level's strength and an entry signal; never a PASS / knife / earnings gate.
// The file has every pattern after a pullback (no zone gate); the zone gate is applied here, live, with the zone that
// counts now (his drawing, else the expert zone). Python twin: confirm_patterns.on_zone / is_entry / on_level.
export type ConfCode = 'engulf' | 'mstar' | 'mdoji' | 'pierce' | 'inside3' | 'hammerc' | 'tweezer';
/** p code, k bars back of the last candle (0 = last completed bar), s / e first / last candle (weekly: Monday),
 *  lo / hi pattern low / high, c last close, a ATR(14) of the same timeframe */
export interface ConfPat { p: ConfCode; k: number; s: string; e: string; lo: number; hi: number; c: number; a: number }
export interface ConfTicker { w: ConfPat[]; d: ConfPat[]; lw: string | null; ld: string | null; px: number | null; wc: number[]; dc?: number[] }
export interface ConfDoc { rule_version: string; generated_at: string; asof: string; consts: Record<string, number>; names: Record<string, string>; sources: Record<string, string>; tickers: Record<string, ConfTicker> }
export interface ConfHit extends ConfPat { tf: 'W' | 'D'; entry: boolean; zsrc?: 'live' | 'expert' }
export interface ConfLevel { w: ConfHit[]; d: ConfHit[]; entry: boolean }

export const CONF_HE: Record<ConfCode, string> = { engulf: 'בליעה שורית', mstar: 'כוכב בוקר', mdoji: "כוכב בוקר דוג'י", pierce: 'קו חודר',
  inside3: 'שלושה מבפנים למעלה', hammerc: 'פטיש + נר אישור', tweezer: 'תחתית פינצטה' };
/** short chart labels */
export const CONF_SHORT: Record<ConfCode, string> = { engulf: 'בליעה', mstar: 'כוכב', mdoji: 'כוכב דוג׳י', pierce: 'חודר', inside3: '3 בפנים', hammerc: 'פטיש+', tweezer: 'פינצטה' };
export const CONF_DEF = { zone_tol_atr: 0.1, zone_tol_pct: 0.01, entry_weeks: 2, entry_days: 5 };

/** the pattern's low actually touches the zone: bottom - tol <= low <= top + tol, tol = min(0.1 ATR, 1% of the top)
 *  (v2, Eyal 2026-11-16 NTRA) */
export function onZone(p: ConfPat, z: { top: number; bottom: number }, tol = CONF_DEF.zone_tol_atr, pct = CONF_DEF.zone_tol_pct): boolean {
  const top = Math.max(z.top, z.bottom), bot = Math.min(z.top, z.bottom), t = Math.min(tol * p.a, pct * Math.abs(top));
  return p.lo >= bot - t && p.lo <= top + t;
}
/** patterns of one ticker on a zone. Entry signal (Python twin confirm_patterns.on_level): weekly ending in the last
 *  entry_weeks completed weeks, or daily (v3, Eyal 2026-11-16: on the weekly zone, daily-ATR tolerance) in the last
 *  entry_days completed sessions; never closed under its low since (closes of that timeframe + the live / last price) */
export function confOnLevel(c: ConfTicker | null | undefined, z: { top: number; bottom: number } | null | undefined, px: number | null,
  consts: Record<string, number> = CONF_DEF): ConfLevel {
  if (!c || !z) return { w: [], d: [], entry: false };
  const tol = consts.zone_tol_atr ?? CONF_DEF.zone_tol_atr, pct = consts.zone_tol_pct ?? CONF_DEF.zone_tol_pct;
  const ew = consts.entry_weeks ?? CONF_DEF.entry_weeks, ed = consts.entry_days ?? CONF_DEF.entry_days;
  const last = px != null ? [px] : c.px != null ? [c.px] : [];
  const hits = (ps: ConfPat[], closes: number[], tf: 'W' | 'D', lim: number) => ps.filter((p) => onZone(p, z, tol, pct)).map((p) => {
    const after = [...(p.k ? closes.slice(closes.length - p.k) : []), ...last];
    return { ...p, tf, entry: p.k < lim && after.every((x) => x >= p.lo) };
  });
  const w = hits(c.w || [], c.wc || [], 'W', ew), d = hits(c.d || [], c.dc || [], 'D', ed);
  return { w, d, entry: w.some((p) => p.entry) || d.some((p) => p.entry) };
}
/** within X weeks: weekly k < X, daily k < 5X sessions */
export function confWithin(l: ConfLevel, weeks: number): ConfHit[] {
  return [...l.w.filter((p) => p.k < weeks), ...l.d.filter((p) => p.k < 5 * weeks)];
}
/** sort key: entry signal first, then a weekly pattern, then a daily one; newer first inside each */
export function confRank(l: ConfLevel): number {
  if (l.entry) { const e = [...l.w, ...l.d].filter((p) => p.entry); return Math.min(...e.map((p) => (p.tf === 'W' ? p.k * 5 : p.k))) / 1000; }
  if (l.w.length) return 1 + Math.min(...l.w.map((p) => p.k)) / 100;
  if (l.d.length) return 2 + Math.min(...l.d.map((p) => p.k)) / 1000;
  return 9;
}
