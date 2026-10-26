// Position sizing for the list card (Eyal 2026-10-24): "how much we risk / earn in $ with up to $50 risk per position".
//   maxRisk = account × max risk % from the dashboard's sizing settings (localStorage 'srs_sizing_v1', shared with
//             index.html / table.html on the same origin; defaults $5000 × 1.1% = $55, Eyal 2026-10-26; was 1% = $50)
//   shares  = floor(maxRisk / (entry − SL));  risk$ = shares × (entry − SL);  reward$ = shares × (TP − entry)
// shares = 0 -> the stop is wider than maxRisk per share (shown as such, not as a 0-share position).
export const SIZING_KEY = 'srs_sizing_v1';
export const SIZING_DEFAULTS = { account: 5000, riskPct: 1.1 };

export function maxRiskUsd(store: Pick<Storage, 'getItem'> | null = typeof localStorage !== 'undefined' ? localStorage : null): number {
  let account = SIZING_DEFAULTS.account, riskPct = SIZING_DEFAULTS.riskPct;
  try {
    const s = JSON.parse(store?.getItem(SIZING_KEY) || '{}');
    const a = parseFloat(s.account), p = parseFloat(s.riskPct);
    if (Number.isFinite(a) && a > 0) account = a;
    if (Number.isFinite(p) && p > 0) riskPct = p;
    if (p === 1 && account === 5000 && !s.r55) riskPct = SIZING_DEFAULTS.riskPct; // old saved default 1% ($50) -> $55
  } catch { /* defaults */ }
  return Math.round(account * riskPct) / 100;
}

export interface Sizing { shares: number; perShare: number; risk: number; reward: number; maxRisk: number; rr: number | null }

/** null = no usable Long (missing level or SL >= entry). */
export function sizeLong(entry: number | null | undefined, stop: number | null | undefined, target: number | null | undefined,
  maxRisk: number): Sizing | null {
  if (entry == null || stop == null || target == null) return null;
  const e = +entry, s = +stop, t = +target;
  if (![e, s, t].every(Number.isFinite)) return null;
  const perShare = e - s;
  if (perShare <= 0) return null;
  const shares = Math.max(0, Math.floor(maxRisk / perShare + 1e-9));
  const r2 = (x: number) => Math.round(x * 100) / 100;
  return { shares, perShare: r2(perShare), risk: r2(shares * perShare), reward: r2(shares * (t - e)), maxRisk, rr: (t - e) / perShare };
}
