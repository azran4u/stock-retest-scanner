// Open positions bar (Eyal 2026-10-24: "at the top of the page always show the open positions and the P/L right now").
// Positions come from Supabase public.positions (owner-only RLS, mirrored from the box's positions.json by
// `positions.py supabase-sql`). Prices: CNBC quote API (real-time, CORS *) -> TradingView scanner (15 min delayed,
// CORS for this origin) -> the stored last close of the nightly refresh ('סגירה אחרונה'). Never a made-up price.

export interface Position {
  id: string; ticker: string; exchange: string | null; side: string; status: string; entry_date: string | null;
  qty: number; entry_price: number; stop: number | null; target: number | null; note?: string | null;
  market?: { date?: string; close?: number; low?: number; high?: number; weekly_atr?: number; fetched_at?: string } | null;
}

export type QuoteSrc = 'cnbc' | 'tv' | 'close';
export interface Quote {
  price: number; src: QuoteSrc;
  /** when the price was made (ISO, absolute) if known */
  at: string | null;
  /** only the trading date is known (e.g. CNBC after the close) */
  date: string | null;
  status?: string | null;           // CNBC curmktstatus: REG_MKT / PRE_MKT / POST_MKT / ...
  ext?: { price: number; kind: string } | null;  // pre / after-market last (shown, not used for P/L)
}

export interface Calc {
  price: number | null; pl: number | null; plPct: number | null; r: number | null;
  toStopPct: number | null; toTgtPct: number | null; cost: number; risk: number | null;
}

const num = (x: unknown): number | null => (x == null || x === '' || Number.isNaN(+(x as any)) ? null : +(x as any));

export function normPosition(row: any): Position {
  return { ...row, qty: +row.qty, entry_price: +row.entry_price, stop: num(row.stop), target: num(row.target) };
}

/** P/L $ = (price − entry) × qty; % = price / entry − 1; R = (price − entry) / (entry − SL);
 *  distance to SL / TP = (level − price) / price (negative = SL below, positive = TP above). */
export function calcPosition(p: Position, price: number | null): Calc {
  const e = p.entry_price, s = p.stop, t = p.target;
  const cost = e * p.qty, risk = s != null && e > s ? (e - s) * p.qty : null;
  if (price == null) return { price: null, pl: null, plPct: null, r: null, toStopPct: null, toTgtPct: null, cost, risk };
  return {
    price,
    pl: (price - e) * p.qty,
    plPct: (price / e - 1) * 100,
    r: s != null && e !== s ? (price - e) / (e - s) : null,
    toStopPct: s != null ? ((s - price) / price) * 100 : null,
    toTgtPct: t != null ? ((t - price) / price) * 100 : null,
    cost, risk,
  };
}

export function totals(cs: Calc[]) {
  const ok = cs.filter((c) => c.pl != null);
  const pl = ok.reduce((a, c) => a + c.pl!, 0), cost = ok.reduce((a, c) => a + c.cost, 0);
  const risk = ok.every((c) => c.risk != null) ? ok.reduce((a, c) => a + c.risk!, 0) : null;
  return { pl: ok.length ? pl : null, plPct: ok.length && cost ? (pl / cost) * 100 : null, r: ok.length && risk ? pl / risk : null, n: ok.length, missing: cs.length - ok.length };
}

// ---------------- quotes ----------------
const ET_OFF: Record<string, string> = { EDT: '-04:00', EST: '-05:00' };

/** CNBC last_time / last_timedate -> absolute ISO time when known, else only the date. */
export function parseCnbcTime(lastTime: string | undefined, lastTimedate: string | undefined): { at: string | null; date: string | null } {
  const lt = lastTime || '';
  const m = lt.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?([+-]\d{2}):?(\d{2})$/);
  if (m) return { at: new Date(`${m[1]}T${m[2]}${m[3]}:${m[4]}`).toISOString(), date: m[1] };
  const d = lt.match(/^(\d{4}-\d{2}-\d{2})/)?.[1] ?? null;
  const tm = (lastTimedate || '').match(/(\d{1,2}):(\d{2})\s*(AM|PM)\s*(EDT|EST)/i);
  if (d && tm) {
    let h = +tm[1] % 12; if (/pm/i.test(tm[3])) h += 12;
    return { at: new Date(`${d}T${String(h).padStart(2, '0')}:${tm[2]}:00${ET_OFF[tm[4].toUpperCase()]}`).toISOString(), date: d };
  }
  return { at: null, date: d };
}

export const CNBC_URL = 'https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol';
export const TV_URL = 'https://scanner.tradingview.com/america/scan';

export async function fetchCnbc(tickers: string[], f: typeof fetch = fetch): Promise<Map<string, Quote>> {
  const out = new Map<string, Quote>();
  if (!tickers.length) return out;
  const u = `${CNBC_URL}?symbols=${encodeURIComponent(tickers.map((t) => t.replace('-', '.')).join('|'))}&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=0`;
  const r = await f(u, { cache: 'no-store' });
  if (!r.ok) throw new Error('cnbc ' + r.status);
  const j = await r.json();
  let q = j?.FormattedQuoteResult?.FormattedQuote ?? [];
  if (!Array.isArray(q)) q = [q];
  for (const x of q) {
    const price = num(String(x?.last ?? '').replace(/,/g, ''));
    if (!x?.symbol || price == null || x.code !== 0 && x.code !== '0' && x.code != null) continue;
    const t = String(x.symbol).toUpperCase().replace('.', '-');
    const { at, date } = parseCnbcTime(x.last_time, x.last_timedate);
    const e = x.ExtendedMktQuote, ep = e ? num(String(e.last ?? '').replace(/,/g, '')) : null;
    out.set(t, { price, src: 'cnbc', at, date, status: x.curmktstatus ?? null, ext: e && ep != null && ep !== price ? { price: ep, kind: e.type } : null });
  }
  return out;
}

export async function fetchTv(ps: Position[], f: typeof fetch = fetch): Promise<Map<string, Quote>> {
  const out = new Map<string, Quote>();
  const syms = ps.filter((p) => p.exchange).map((p) => `${p.exchange!.toUpperCase()}:${p.ticker.replace('-', '.')}`);
  if (!syms.length) return out;
  // text/plain keeps it a "simple" CORS request (no preflight)
  const r = await f(TV_URL, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ symbols: { tickers: syms }, columns: ['close'] }) });
  if (!r.ok) throw new Error('tv ' + r.status);
  const j = await r.json();
  const now = new Date();
  for (const d of j?.data ?? []) {
    const price = num(d?.d?.[0]);
    if (price == null) continue;
    const t = String(d.s).split(':')[1].replace('.', '-');
    out.set(t, { price, src: 'tv', at: now.toISOString(), date: null }); // fetch time; the quote itself is ~15 min delayed
  }
  return out;
}

/** Freshest price per open position: CNBC, else TradingView, else the stored nightly close. */
export async function fetchQuotes(ps: Position[], f: typeof fetch = fetch): Promise<Map<string, Quote>> {
  const tick = [...new Set(ps.map((p) => p.ticker))];
  let q = new Map<string, Quote>();
  try { q = await fetchCnbc(tick, f); } catch { /* fall through */ }
  const miss = ps.filter((p) => !q.has(p.ticker));
  if (miss.length) { try { for (const [k, v] of await fetchTv(miss, f)) q.set(k, v); } catch { /* fall through */ } }
  for (const p of ps) {
    const c = num(p.market?.close);
    if (!q.has(p.ticker) && c != null) q.set(p.ticker, { price: c, src: 'close', at: null, date: p.market?.date ?? null });
  }
  return q;
}

// ---------------- formatting ----------------
const IL = 'Asia/Jerusalem';
export function ilTime(iso: string): string {
  const d = new Date(iso), now = new Date();
  const day = (x: Date) => x.toLocaleDateString('sv-SE', { timeZone: IL });
  const hm = d.toLocaleTimeString('he-IL', { timeZone: IL, hour: '2-digit', minute: '2-digit', hour12: false });
  return day(d) === day(now) ? hm : `${dm(day(d))} ${hm}`;
}
export const dm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
export function quoteLabel(q: Quote | undefined): string {
  if (!q) return 'אין מחיר';
  const st = q.status === 'REG_MKT' ? '' : q.status === 'PRE_MKT' ? ' · לפני פתיחה' : q.status === 'POST_MKT' ? ' · אחרי סגירה' : q.status ? ' · שוק סגור' : '';
  if (q.src === 'cnbc') return q.at ? `CNBC ${ilTime(q.at)} (שעון ישראל)${st}` : `CNBC · מחיר סגירה ${q.date ? dm(q.date) : ''}`;
  if (q.src === 'tv') return `TradingView · מושהה ~15 דק׳ · נמשך ${ilTime(q.at!)} (שעון ישראל)`;
  return `סגירה אחרונה ${q.date ? dm(q.date) : ''}`;
}
