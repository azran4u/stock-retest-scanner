// Confirmation candlestick patterns on the retest level (Eyal 2026-11-16, srs_app/confirm_patterns.py -> confirm.json).
// Evidence only: a confirmation of the level's strength and an entry signal; never a PASS / knife / earnings gate.
// The file has every pattern after a pullback (no zone gate); the zone gate is applied here, live, with the zone that
// counts now (his drawing, else the expert zone). Python twin: confirm_patterns.on_zone / is_entry / on_level.
export type ConfCode = 'engulf' | 'mstar' | 'mdoji' | 'pierce' | 'inside3' | 'hammerc' | 'tweezer';
/** p code, k bars back of the last candle (0 = last completed bar), s / e first / last candle (weekly: Monday),
 *  lo / hi pattern low / high, c last close, a ATR(14) of the same timeframe */
export interface ConfPat { p: ConfCode; k: number; s: string; e: string; lo: number; hi: number; c: number; a: number }
export interface ConfTicker { w: ConfPat[]; d: ConfPat[]; lw: string | null; ld: string | null; px: number | null; wc: number[] }
export interface ConfDoc { rule_version: string; generated_at: string; asof: string; consts: Record<string, number>; names: Record<string, string>; sources: Record<string, string>; tickers: Record<string, ConfTicker> }
export interface ConfHit extends ConfPat { tf: 'W' | 'D'; entry: boolean; zsrc?: 'live' | 'expert' }
export interface ConfLevel { w: ConfHit[]; d: ConfHit[]; entry: boolean }

export const CONF_HE: Record<ConfCode, string> = { engulf: 'בליעה שורית', mstar: 'כוכב בוקר', mdoji: "כוכב בוקר דוג'י", pierce: 'קו חודר',
  inside3: 'שלושה מבפנים למעלה', hammerc: 'פטיש + נר אישור', tweezer: 'תחתית פינצטה' };
/** short chart labels */
export const CONF_SHORT: Record<ConfCode, string> = { engulf: 'בליעה', mstar: 'כוכב', mdoji: 'כוכב דוג׳י', pierce: 'חודר', inside3: '3 בפנים', hammerc: 'פטיש+', tweezer: 'פינצטה' };
export const CONF_DEF = { zone_tol_atr: 0.5, entry_weeks: 2 };

/** the pattern's low touches the zone: low <= top + tol*ATR and (low >= bottom - tol*ATR or last close >= bottom) */
export function onZone(p: ConfPat, z: { top: number; bottom: number }, tol = CONF_DEF.zone_tol_atr): boolean {
  const top = Math.max(z.top, z.bottom), bot = Math.min(z.top, z.bottom), t = tol * p.a;
  return p.lo <= top + t && (p.lo >= bot - t || p.c >= bot);
}
/** patterns of one ticker on a zone; weekly ones ending in the last entry_weeks completed weeks, never closed under
 *  their low since (completed weekly closes + the live / last price), are an entry signal */
export function confOnLevel(c: ConfTicker | null | undefined, z: { top: number; bottom: number } | null | undefined, px: number | null,
  consts: Record<string, number> = CONF_DEF): ConfLevel {
  if (!c || !z) return { w: [], d: [], entry: false };
  const tol = consts.zone_tol_atr ?? CONF_DEF.zone_tol_atr, ew = consts.entry_weeks ?? CONF_DEF.entry_weeks;
  const wc = c.wc || [];
  const w = (c.w || []).filter((p) => onZone(p, z, tol)).map((p) => {
    const after = [...(p.k ? wc.slice(wc.length - p.k) : []), ...(px != null ? [px] : c.px != null ? [c.px] : [])];
    return { ...p, tf: 'W' as const, entry: p.k < ew && after.every((x) => x >= p.lo) };
  });
  const d = (c.d || []).filter((p) => onZone(p, z, tol)).map((p) => ({ ...p, tf: 'D' as const, entry: false }));
  return { w, d, entry: w.some((p) => p.entry) };
}
/** within X weeks: weekly k < X, daily k < 5X sessions */
export function confWithin(l: ConfLevel, weeks: number): ConfHit[] {
  return [...l.w.filter((p) => p.k < weeks), ...l.d.filter((p) => p.k < 5 * weeks)];
}
/** sort key: entry signal first, then a weekly pattern, then a daily one; newer first inside each */
export function confRank(l: ConfLevel): number {
  if (l.entry) return 0 + Math.min(...l.w.filter((p) => p.entry).map((p) => p.k)) / 100;
  if (l.w.length) return 1 + Math.min(...l.w.map((p) => p.k)) / 100;
  if (l.d.length) return 2 + Math.min(...l.d.map((p) => p.k)) / 1000;
  return 9;
}
