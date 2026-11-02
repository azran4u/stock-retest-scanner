import { assert, assertEquals } from 'jsr:@std/assert@1';
import { classify, earningsNote, marketOpen, message, nyClock, pickLevel } from './logic.ts';

Deno.test('NY clock handles DST and the session', () => {
  const s = nyClock(new Date('2026-07-01T13:35:00Z'));            // EDT: 09:35
  assertEquals([s.date, s.minutes, marketOpen(s).open], ['2026-07-01', 9 * 60 + 35, true]);
  const w = nyClock(new Date('2026-11-02T14:25:00Z'));            // EST: 09:25 -> pre-market
  assertEquals([w.minutes, marketOpen(w).why], [9 * 60 + 25, 'pre-market']);
  assert(marketOpen(nyClock(new Date('2026-11-02T20:59:00Z'))).open);   // 15:59 EST
  assertEquals(marketOpen(nyClock(new Date('2026-11-02T21:10:00Z'))).why, 'after close');
  assertEquals(marketOpen(nyClock(new Date('2026-11-26T15:00:00Z'))).why, 'holiday');   // Thanksgiving
  assertEquals(marketOpen(nyClock(new Date('2026-11-27T18:30:00Z'))).why, 'after close'); // early close 13:00
  assertEquals(marketOpen(nyClock(new Date('2026-11-07T15:00:00Z'))).why, 'weekend');
});

Deno.test('level: own Long (user/tv) > expert > bot', () => {
  const z = { ok: true, atr_w: 5, trade: { entry: 75.79, sl: 70.1, tp: 95.44, rr: 3.45 } };
  const own = pickLevel('DAL', [{ source: 'bot', entry: 70, stop: 60, target: 90, updated_at: '2026-10-31' },
    { source: 'tv', entry: 75.66, stop: 65.16, target: 92.87, updated_at: '2026-10-20' }], z)!;
  assertEquals([own.src, own.entry, own.rr], ['own', 75.66, 1.64]);
  assertEquals(pickLevel('DAL', [{ source: 'bot', entry: 70, stop: 60, target: 90 }], z)!.src, 'expert');
  const b = pickLevel('X', [{ source: 'bot', entry: 70, stop: 60, target: 90 }], { ok: false, atr_w: 2 })!;
  assertEquals([b.src, b.rr, b.atr], ['bot', 2, 2]);
  assertEquals(pickLevel('Y', [], { ok: false }), null);
});

Deno.test('touch uses the intraday range and gaps; near = 0.25 ATR', () => {
  const l = { ticker: 'T', entry: 100, stop: 95, target: 115, rr: 3, src: 'expert' as const, atr: 4 };
  assert(classify(l, { price: 102, dayHigh: 103, dayLow: 99.9, prevClose: 104 }).touch);      // wick touched, back up
  const g = classify(l, { price: 98, dayHigh: 99, dayLow: 97, prevClose: 101 });               // gapped through
  assert(g.touch && g.crossed);
  assert(message('touch', l, { price: 98, dayHigh: 99, dayLow: 97, prevClose: 101 }, g.distAtr, null, g.crossed).includes('בפער מסגירה קודמת 101.00'));
  const n = classify(l, { price: 100.9, dayHigh: 102, dayLow: 100.5, prevClose: 102 });
  assertEquals([n.touch, n.near, n.distAtr], [false, true, 0.225]);
  assertEquals(classify(l, { price: 101.2, dayHigh: 102, dayLow: 101.1, prevClose: 102 }).near, false);  // 0.3 ATR
  assertEquals(classify({ ...l, atr: null }, { price: 100.5, dayHigh: 101, dayLow: 100.4, prevClose: 101 }).near, false);
});

Deno.test('earnings note and Hebrew message', () => {
  assertEquals(earningsNote({ n: '2026-11-05', nt: 'bmo' }, '2026-11-02'), '⚠️ דוחות בעוד 3 ימים (2026-11-05 bmo)');
  assertEquals(earningsNote({ n: '2027-01-27', p: [{ d: '2026-10-21' }] }, '2026-11-02'), null);
  assertEquals(earningsNote({ n: '2027-01-27', p: [{ d: '2026-10-28' }] }, '2026-10-30'), '⚠️ שבוע דוחות (2026-10-28)');
  const m = message('near', { ticker: 'DAL', entry: 75.66, stop: 65.16, target: 92.87, rr: 1.64, src: 'own', atr: 5.69 },
    { price: 76.5, dayHigh: 77, dayLow: 76.2, prevClose: 77.5 }, 0.148, null);
  assert(m.startsWith('⏳ DAL מתקרבת לכניסה'));
  assert(m.includes('כניסה: 75.66 (ה-Long שלך)') && m.includes('0.15 ATR שבועי מעל') && m.includes('R:R 1.64'));
  assert(m.endsWith('https://retest-scanner.vercel.app/#/t/DAL'));
});
