// Pure logic of the real-time price alerts (srs-price-alerts). No I/O here so it is unit-tested with `deno test`.
// Actionable-only alerts (Eyal 2026-11-02: "אל תשלח הודעה אם אין לי מה לעשות איתה"). Rules: supabase/README.md.
export const NEAR_ATR = 0.25;          // a limit at the entry is suggested while price is <= 0.25 weekly ATR above it (approaching)
export const RUN_ATR = 0.5;            // "entry triggered" only while price is still <= 0.5 ATR above the entry (not run away)
export const MIN_RR = 2;
export const RISK_USD = 55;
export const COOLDOWN_DAYS: Record<string, number> = { limit: 5, triggered: 5, cancel: 30 };
export const EARN_DAYS = 14;
export const APP_URL = 'https://retest-scanner.vercel.app/';

// NYSE full-day holidays and 13:00 ET early closes (nyse.com, 2026-2027)
export const HOLIDAYS = new Set([
  '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
  '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
]);
export const EARLY_CLOSE = new Set(['2026-11-27', '2026-12-24', '2027-11-26']);

export interface NyClock { date: string; dow: number; minutes: number }
/** Wall clock in America/New_York (DST handled by Intl). */
export function nyClock(now: Date): NyClock {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short' }).formatToParts(now).map((x) => [x.type, x.value]));
  const dow = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(p.weekday);
  return { date: `${p.year}-${p.month}-${p.day}`, dow, minutes: Number(p.hour) * 60 + Number(p.minute) };
}
/** Regular session 09:30-16:00 ET (13:00 on early closes), weekdays, not a holiday. A 5-minute grace after the
 *  close lets the last 10-minute run see the closing range. */
export function marketOpen(c: NyClock): { open: boolean; why: string } {
  if (c.dow === 0 || c.dow === 6) return { open: false, why: 'weekend' };
  if (HOLIDAYS.has(c.date)) return { open: false, why: 'holiday' };
  const close = EARLY_CLOSE.has(c.date) ? 13 * 60 : 16 * 60;
  if (c.minutes < 9 * 60 + 30) return { open: false, why: 'pre-market' };
  if (c.minutes > close + 5) return { open: false, why: 'after close' };
  return { open: true, why: 'open' };
}

export type Kind = 'limit' | 'triggered' | 'cancel';
export type Src = 'own' | 'expert';
export const SRC_HE: Record<Src, string> = { own: 'שלך', expert: 'מומחים' };

/** The setup of one tracked ticker: Eyal's own Long (+ his zone) overrides the expert trade + zone. */
export interface Setup {
  ticker: string; src: Src; entry: number; stop: number; target: number; rr: number;
  zoneTop: number; zoneBottom: number; atr: number | null;
  starred: boolean; hot: boolean; expertOk: boolean; uptrend: boolean | null;
  /** falling knife (Eyal 2026-11-09): last completed weekly candle = healthy red bar on above-average volume (index.json
   *  f_no_red_vol_week === false) -> no limit / triggered alert until the next weekly close; cancel alerts unchanged */
  knife?: boolean;
}
const rrOf = (e: number, s: number, t: number) => (e > s ? Math.round(((t - e) / (e - s)) * 100) / 100 : 0);
const num = (v: any) => (v == null || v === '' ? null : Number(v));
const newest = (xs: any[]) => [...xs].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0];

export function buildSetup(ticker: string, drawings: any[], zone: any, o: { starred: boolean; hot: boolean; uptrend: boolean | null; knife?: boolean }): Setup | null {
  const mine = drawings.filter((d) => d.source === 'user' || d.source === 'tv');
  const myLong = newest(mine.filter((d) => d.kind === 'long' && d.entry != null && d.stop != null && d.target != null));
  const myZone = newest(mine.filter((d) => d.kind === 'zone' && d.zone_top != null));
  const ok = !!(zone?.ok && zone.trade);
  const atr = num(zone?.atr_w);
  if (myLong) {
    const e = Number(myLong.entry), s = Number(myLong.stop), t = Number(myLong.target);
    const zt = myZone ? Number(myZone.zone_top) : ok ? zone.top : e, zb = myZone ? Number(myZone.zone_bottom) : ok ? zone.bottom : e;
    return { ticker, src: 'own', entry: e, stop: s, target: t, rr: rrOf(e, s, t), zoneTop: zt, zoneBottom: zb, atr, ...o, expertOk: ok };
  }
  if (!ok) return null;                     // no clear retest -> no zone, no Long -> nothing to do
  const tr = zone.trade;
  return { ticker, src: 'expert', entry: tr.entry, stop: tr.sl, target: tr.tp, rr: tr.rr ?? rrOf(tr.entry, tr.sl, tr.tp),
           zoneTop: zone.top, zoneBottom: zone.bottom, atr, ...o, expertOk: true };
}

/** Earnings blocks a new entry: next report within EARN_DAYS days, or a report reacted to this week / in the last
 *  completed week (amc -> next weekday). earnings.json {T: {p: [{d, t}], n, nt}}. */
export function earningsBlock(em: any, today: string): string | null {
  if (!em) return null;
  const day = (s: string) => Date.parse(s.slice(0, 10) + 'T00:00:00Z') / 86400000;
  const t0 = day(today), dow = (new Date(t0 * 86400000).getUTCDay() + 6) % 7, mon = t0 - dow;
  if (em.n) { const dd = day(em.n) - t0; if (dd >= 0 && dd < EARN_DAYS) return `דוחות בעוד ${dd} ימים (${em.n})`; }
  for (const p of [...(em.p || []), ...(em.n ? [{ d: em.n, t: em.nt }] : [])]) {
    let d = day(p.d); const wd = (new Date(d * 86400000).getUTCDay() + 6) % 7;
    if (p.t === 'amc') d += wd === 4 ? 3 : 1;
    if (d >= mon - 7 && d <= t0) return `שבוע דוחות (${String(p.d).slice(0, 10)})`;
  }
  return null;
}

export const KNIFE_HE = 'נר אדום בריא במחזור גבוה — ממתינים לסגירת השבוע הבא';
/** Why the setup is not tradable now (null = valid): zone intact, R:R >= 2, earnings clear, uptrend, no falling knife. */
export function invalidWhy(s: Setup, earn: string | null): string | null {
  if (s.src === 'expert' && !s.expertOk) return 'אין אזור מומחים תקף';
  if (!(s.rr >= MIN_RR)) return `R:R ${s.rr.toFixed(2)} < ${MIN_RR}`;
  if (earn) return earn;
  if (s.uptrend === false) return 'לא במגמת עלייה ראשית';
  if (s.knife) return KNIFE_HE;
  return null;
}

export interface Quote { price: number; dayHigh: number; dayLow: number; prevClose: number | null }
export interface Decision { kind: Kind | null; why: string; distAtr: number | null }
/** Trader rules (supabase/README.md):
 *  cancel    - price <= SL (or the expert zone is no longer valid) and an order may be working: a limit / triggered
 *              alert was sent for this entry, or the stock is starred. Once per level.
 *  triggered - the session traded at / under the entry and price is back above it, still <= RUN_ATR above (the
 *              limit would have filled and the trade is still enterable). Setup must be valid.
 *  limit     - price inside the zone or <= NEAR_ATR above the entry, not triggered today, setup valid: place a buy
 *              limit at the entry (price above it) or a buy-stop at the entry (price inside the zone, under it).
 *  nothing   - setup invalid, price ran away (> NEAR_ATR above), price under the zone but above SL (moving away /
 *              breaking down, no order to place), or no ATR. */
export function decide(s: Setup, q: Quote, earn: string | null, hadOrder: boolean): Decision {
  const A = s.atr; const distAtr = A ? Math.round(((q.price - s.entry) / A) * 1000) / 1000 : null;
  if (q.price <= s.stop || (s.src === 'expert' && !s.expertOk)) {
    return (hadOrder || s.starred) ? { kind: 'cancel', why: q.price <= s.stop ? 'price <= SL' : 'zone invalid', distAtr } : { kind: null, why: 'broken, no order', distAtr };
  }
  const bad = invalidWhy(s, earn);
  if (bad) return { kind: null, why: 'invalid: ' + bad, distAtr };
  if (!A || distAtr == null) return { kind: null, why: 'no ATR', distAtr };
  if (q.price < s.zoneBottom) return { kind: null, why: 'under the zone', distAtr };
  if (q.dayLow <= s.entry && q.price > s.entry && distAtr <= RUN_ATR) return { kind: 'triggered', why: 'filled today, still near', distAtr };
  if (distAtr > NEAR_ATR) return { kind: null, why: 'ran away / far above', distAtr };
  return { kind: 'limit', why: q.price > s.entry ? 'near above the entry' : 'inside the zone', distAtr };
}

export const shares = (s: Setup) => (s.entry > s.stop ? Math.floor(RISK_USD / (s.entry - s.stop)) : 0);
const f2 = (v: number | null | undefined) => (v == null || !isFinite(v) ? '—' : v.toFixed(2));
export function message(kind: Kind, s: Setup, q: Quote, d: Decision, note: string | null = null): string {
  const n = shares(s), tag = [s.starred ? '⭐' : '', s.hot ? '🔥 רשימה חמה' : ''].filter(Boolean).join(' ');
  const dist = d.distAtr == null ? '' : `${Math.abs(d.distAtr).toFixed(2)} ATR ${d.distAtr >= 0 ? 'מעל ה' : 'מתחת ל'}כניסה`;
  const plan = `SL ${f2(s.stop)} · TP ${f2(s.target)} · R:R ${s.rr.toFixed(2)} · ${n} מניות (סיכון $${RISK_USD})`;
  const link = `${APP_URL}#/t/${encodeURIComponent(s.ticker)}`;
  const zone = `אזור ${f2(s.zoneBottom)}–${f2(s.zoneTop)} (${SRC_HE[s.src]})`;
  let lines: string[];
  if (kind === 'limit') {
    const order = q.price > s.entry ? `לימיט קנייה ב-${f2(s.entry)}` : `Buy-Stop ב-${f2(s.entry)} (המחיר בתוך האזור, נכנסים כשחוזר מעל)`;
    lines = [`📌 ${s.ticker} — שווה לשים פקודה ${tag}`, `מחיר ${f2(q.price)} · ${dist}`, `פקודה: ${order}`, plan, zone];
  } else if (kind === 'triggered') {
    lines = [`✅ ${s.ticker} — הכניסה הופעלה ${tag}`, `נגעה היום ב-${f2(q.dayLow)} וחזרה ל-${f2(q.price)} (${dist})`,
      `כניסה ${f2(s.entry)} עדיין בטווח (עד ${RUN_ATR} ATR). אם אין לך פוזיציה — אפשר להיכנס עכשיו`, plan, zone];
  } else {
    lines = [`❌ ${s.ticker} — בטל את הפקודה ${tag}`,
      q.price <= s.stop ? `המחיר ${f2(q.price)} ירד מתחת ל-SL ${f2(s.stop)} — הסטאפ נשבר` : `אזור המומחים כבר לא תקף — הסטאפ בוטל`,
      `אם יש פקודת קנייה פתוחה ב-${f2(s.entry)} — לבטל`, zone];
  }
  if (note) lines.push(note);
  lines.push(link);
  return lines.filter(Boolean).join('\n');
}

/** Cross-day cooldown: the same kind for the same entry level is not repeated for COOLDOWN_DAYS[kind] days unless the
 *  levels changed (entry / SL / TP moved > 0.5%). recent = earlier live alerts of this ticker {kind, entry, stop, target, trade_day}. */
export function coolingDown(kind: Kind, s: Setup, recent: any[], today: string): boolean {
  const same = (a: any, b: number) => a != null && Math.abs(Number(a) - b) <= Math.abs(b) * 0.005;
  const t0 = Date.parse(today + 'T00:00:00Z');
  return recent.some((r) => r.kind === kind && same(r.entry, s.entry) && same(r.stop, s.stop) && same(r.target, s.target)
    && (t0 - Date.parse(String(r.trade_day).slice(0, 10) + 'T00:00:00Z')) / 86400000 < COOLDOWN_DAYS[kind]);
}
/** an order may be working for this level: a limit / triggered alert was sent for it in the last 30 days */
export const hadOrder = (s: Setup, recent: any[]) => recent.some((r) => (r.kind === 'limit' || r.kind === 'triggered') && Math.abs(Number(r.entry) - s.entry) <= Math.abs(s.entry) * 0.005);
