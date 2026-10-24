// Positions bar math + quote parsing (src/positions.ts). Usage: node test_positions.mjs  (exits 1 on any failure)
import { buildSync } from 'esbuild';
import { mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const out = join(mkdtempSync(join(tmpdir(), 'pos-')), 'pos.mjs');
buildSync({ entryPoints: [new URL('./src/positions.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node' });
const P = await import(out);
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const near = (a, b) => Math.abs(a - b) < 1e-9;
const p = { id: 'X:2026-01-02', ticker: 'X', exchange: 'NYSE', side: 'long', status: 'open', entry_date: '2026-01-02', qty: 4, entry_price: 50, stop: 45, target: 65 };
let c = P.calcPosition(p, 53);
ok(near(c.pl, 12) && near(c.plPct, 6) && near(c.r, 0.6) && near(c.toStopPct, (45 - 53) / 53 * 100) && near(c.toTgtPct, (65 - 53) / 53 * 100), `calc: P/L ${c.pl} ${c.plPct}% R ${c.r} SL ${c.toStopPct.toFixed(2)}% TP ${c.toTgtPct.toFixed(2)}%`);
c = P.calcPosition(p, null);
ok(c.pl == null && c.r == null, 'no price -> no P/L (never invented)');
const q = { ...p, id: 'Y', qty: 2, entry_price: 100, stop: 90, target: null };
const t = P.totals([P.calcPosition(p, 53), P.calcPosition(q, 95)]);
ok(near(t.pl, 12 - 10) && near(t.plPct, 2 / 400 * 100) && near(t.r, 2 / (20 + 20)), `totals: ${t.pl} ${t.plPct}% ${t.r}R`);
ok(P.totals([P.calcPosition(p, null)]).pl == null, 'totals with no prices -> —');
let x = P.parseCnbcTime('2026-10-23T15:59:59.000-0400', '3:59 PM EDT');
ok(x.at === '2026-10-23T19:59:59.000Z' && x.date === '2026-10-23', 'CNBC ISO last_time ' + x.at);
x = P.parseCnbcTime('2026-10-23', '11:05 AM EDT');
ok(x.at === '2026-10-23T15:05:00.000Z', 'CNBC date + "11:05 AM EDT" ' + x.at);
x = P.parseCnbcTime('2026-12-01', '1:30 PM EST');
ok(x.at === '2026-12-01T18:30:00.000Z', 'EST ' + x.at);
x = P.parseCnbcTime('2026-10-23', '10/23/26 EDT');
ok(x.at === null && x.date === '2026-10-23', 'date-only (after the close) -> no time, date kept');
// fetchQuotes fallback chain with a fake fetch
const mk = (cnbc, tv) => async (u) => {
  if (u.startsWith(P.CNBC_URL)) { if (!cnbc) throw new Error('net'); return { ok: true, json: async () => cnbc }; }
  if (u.startsWith(P.TV_URL)) { if (!tv) throw new Error('net'); return { ok: true, json: async () => tv }; }
  throw new Error(u);
};
const ps = [{ ...p, market: { close: 52, date: '2026-10-23' } }, { ...q, ticker: 'BRK-B', exchange: 'NYSE', market: null }];
const cn = { FormattedQuoteResult: { FormattedQuote: [{ symbol: 'X', code: 0, last: '1,053.10', last_time: '2026-10-23T15:59:59.000-0400', last_timedate: '3:59 PM EDT', curmktstatus: 'POST_MKT', ExtendedMktQuote: { type: 'POST_MKT', last: '1,054.00' } }] } };
let m = await P.fetchQuotes(ps, mk(cn, { data: [{ s: 'NYSE:BRK.B', d: [480.5] }] }));
ok(m.get('X').src === 'cnbc' && m.get('X').price === 1053.1 && m.get('X').ext.price === 1054, 'CNBC price parsed (thousands sep, ext-hours kept apart)');
ok(m.get('BRK-B').src === 'tv' && m.get('BRK-B').price === 480.5, 'missing in CNBC -> TradingView (BRK.B <-> BRK-B)');
m = await P.fetchQuotes(ps, mk(null, null));
ok(m.get('X').src === 'close' && m.get('X').price === 52 && !m.has('BRK-B'), 'both down -> stored last close, none for a position without one');
ok(/סגירה אחרונה 23\/10/.test(P.quoteLabel(m.get('X'))) && P.quoteLabel(undefined) === 'אין מחיר', 'labels: ' + P.quoteLabel(m.get('X')));
