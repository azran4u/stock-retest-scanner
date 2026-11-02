// Pure logic of the real-time price alerts (srs-price-alerts). No I/O here so it is unit-tested with `deno test`.
export const NEAR_ATR = 0.25;          // "מתקרבת": |price - entry| <= 0.25 weekly ATR
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

export interface Level { ticker: string; entry: number; stop: number | null; target: number | null; rr: number | null; src: 'own' | 'expert' | 'bot'; atr: number | null }
export const SRC_HE: Record<Level['src'], string> = { own: 'ה-Long שלך', expert: 'אזור המומחים', bot: 'Long של הבוט' };

const rrOf = (e: number, s: number | null, t: number | null) => (s != null && t != null && e > s ? Math.round(((t - e) / (e - s)) * 100) / 100 : null);
/** Entry level of one starred ticker: Eyal's own Long (drawn in the app = 'user', or in TradingView = 'tv', newest first),
 *  else the expert trade (expert_zones.json, valid zone), else the bot's Long as a last resort. */
export function pickLevel(ticker: string, longs: any[], zone: any): Level | null {
  const atr = zone?.atr_w ?? null;
  const mine = longs.filter((d) => d.source === 'user' || d.source === 'tv').sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  const n = (v: any) => (v == null ? null : Number(v));
  if (mine.length && mine[0].entry != null) {
    const d = mine[0]; const e = Number(d.entry);
    return { ticker, entry: e, stop: n(d.stop), target: n(d.target), rr: rrOf(e, n(d.stop), n(d.target)), src: 'own', atr };
  }
  if (zone?.ok && zone.trade?.entry != null) {
    const t = zone.trade;
    return { ticker, entry: t.entry, stop: t.sl ?? null, target: t.tp ?? null, rr: t.rr ?? rrOf(t.entry, t.sl, t.tp), src: 'expert', atr };
  }
  const bot = longs.filter((d) => d.source === 'bot' && d.entry != null).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  if (bot.length) { const d = bot[0]; const e = Number(d.entry); return { ticker, entry: e, stop: n(d.stop), target: n(d.target), rr: rrOf(e, n(d.stop), n(d.target)), src: 'bot', atr }; }
  return null;
}

export interface Quote { price: number; dayHigh: number; dayLow: number; prevClose: number | null; hi?: number; lo?: number }
/** 'touch' = the session's range reached the entry (intraday high/low, so a quick touch between two runs is not missed),
 *  or price crossed it vs the previous close (gap through the level); 'near' = within NEAR_ATR weekly ATR. */
export function classify(l: Level, q: Quote): { touch: boolean; near: boolean; distAtr: number | null; crossed: boolean } {
  const lo = Math.min(q.dayLow, q.lo ?? Infinity), hi = Math.max(q.dayHigh, q.hi ?? -Infinity);
  const crossed = q.prevClose != null && (q.prevClose - l.entry) * (q.price - l.entry) < 0;
  const inRange = lo <= l.entry && l.entry <= hi;
  const touch = inRange || crossed;
  const distAtr = l.atr ? Math.round(((q.price - l.entry) / l.atr) * 1000) / 1000 : null;
  const near = !touch && distAtr != null && Math.abs(distAtr) <= NEAR_ATR;
  return { touch, near, distAtr, crossed: crossed && !inRange };
}

/** Earnings note: next report within EARN_DAYS days, or a report in the current Mon-Fri week. earnings.json {T: {p:[{d,t}], n, nt}}. */
export function earningsNote(em: any, today: string): string | null {
  if (!em) return null;
  const day = (s: string) => Date.parse(s.slice(0, 10) + 'T00:00:00Z') / 86400000;
  const t0 = day(today), dow = (new Date(t0 * 86400000).getUTCDay() + 6) % 7, mon = t0 - dow;
  if (em.n) {
    const dd = day(em.n) - t0;
    if (dd >= 0 && dd < EARN_DAYS) return `⚠️ דוחות בעוד ${dd} ימים (${em.n}${em.nt ? ' ' + em.nt : ''})`;
  }
  for (const p of [...(em.p || []), ...(em.n ? [{ d: em.n }] : [])]) {
    const d = day(p.d);
    if (d >= mon && d <= mon + 4) return `⚠️ שבוע דוחות (${p.d.slice(0, 10)})`;
  }
  return null;
}

const f2 = (v: number | null | undefined) => (v == null || !isFinite(v) ? '—' : v.toFixed(2));
export function message(kind: 'near' | 'touch', l: Level, q: Quote, distAtr: number | null, earn: string | null, crossed = false): string {
  const head = kind === 'touch' ? `🎯 ${l.ticker} נגעה בכניסה` : `⏳ ${l.ticker} מתקרבת לכניסה`;
  const dist = distAtr == null ? '' : `${Math.abs(distAtr).toFixed(2)} ATR שבועי ${distAtr >= 0 ? 'מעל' : 'מתחת'} לכניסה`;
  const lines = [
    head,
    `מחיר: ${f2(q.price)} · כניסה: ${f2(l.entry)} (${SRC_HE[l.src]})`,
    dist && `מרחק: ${dist}`,
    kind === 'touch' ? (crossed ? `חצתה את הכניסה בפער מסגירה קודמת ${f2(q.prevClose)} (טווח היום ${f2(q.dayLow)}–${f2(q.dayHigh)})` : `טווח היום: ${f2(q.dayLow)}–${f2(q.dayHigh)}`) : '',
    `SL ${f2(l.stop)} · TP ${f2(l.target)} · R:R ${l.rr == null ? '—' : l.rr.toFixed(2)}`,
    earn || '',
    `${APP_URL}#/t/${encodeURIComponent(l.ticker)}`,
  ];
  return lines.filter(Boolean).join('\n');
}
