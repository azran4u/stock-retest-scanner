import { assert, assertEquals } from 'jsr:@std/assert@1';
import { buildSetup, coolingDown, decide, earningsBlock, hadOrder, marketOpen, message, nyClock, shares, type Setup } from './logic.ts';

Deno.test('NY clock handles DST and the session', () => {
  const s = nyClock(new Date('2026-07-01T13:35:00Z'));
  assertEquals([s.date, s.minutes, marketOpen(s).open], ['2026-07-01', 9 * 60 + 35, true]);
  assertEquals(marketOpen(nyClock(new Date('2026-11-02T14:25:00Z'))).why, 'pre-market');
  assert(marketOpen(nyClock(new Date('2026-11-02T20:59:00Z'))).open);
  assertEquals(marketOpen(nyClock(new Date('2026-11-26T15:00:00Z'))).why, 'holiday');
  assertEquals(marketOpen(nyClock(new Date('2026-11-27T18:30:00Z'))).why, 'after close');
});

const Z = { ok: true, top: 75.79, bottom: 74.37, atr_w: 5.69, trade: { entry: 75.79, sl: 70.1, tp: 95.44, rr: 3.45 } };
const O = { starred: true, hot: false, uptrend: true };
Deno.test('setup: his Long + zone override the expert trade; no expert zone + no Long -> nothing', () => {
  const own = buildSetup('DAL', [{ source: 'tv', kind: 'long', entry: 75.66, stop: 65.16, target: 92.87, updated_at: '2026-10-20' }], Z, O)!;
  assertEquals([own.src, own.entry, own.rr, own.zoneTop], ['own', 75.66, 1.64, 75.79]);
  assertEquals(buildSetup('DAL', [], Z, O)!.src, 'expert');
  assertEquals(buildSetup('X', [], { ok: false, atr_w: 2 }, O), null);
});

const S: Setup = { ticker: 'DAL', src: 'expert', entry: 75.79, stop: 70.1, target: 95.44, rr: 3.45, zoneTop: 75.79, zoneBottom: 74.37,
  atr: 5.69, starred: false, hot: true, expertOk: true, uptrend: true };
Deno.test('decide: limit near above / inside the zone, triggered, ran away, invalid, broken', () => {
  assertEquals(decide(S, { price: 76.9, dayHigh: 78, dayLow: 76.5, prevClose: 78 }, null, false).kind, 'limit');          // 0.2 ATR above
  assertEquals(decide(S, { price: 75.0, dayHigh: 76, dayLow: 74.8, prevClose: 75.5 }, null, false).kind, 'limit');       // inside: buy-stop
  assertEquals(decide(S, { price: 76.5, dayHigh: 77, dayLow: 75.5, prevClose: 77 }, null, false).kind, 'triggered');     // dipped under, back
  assertEquals(decide(S, { price: 80.2, dayHigh: 81, dayLow: 75.6, prevClose: 80 }, null, false).kind, null);            // ran away (0.78 ATR)
  assertEquals(decide(S, { price: 77.5, dayHigh: 78, dayLow: 77, prevClose: 78 }, 'דוחות בעוד 3 ימים', false).kind, null);
  assertEquals(decide({ ...S, rr: 1.8 }, { price: 76, dayHigh: 77, dayLow: 76, prevClose: 77 }, null, false).kind, null);
  assertEquals(decide({ ...S, uptrend: false }, { price: 76, dayHigh: 77, dayLow: 76, prevClose: 77 }, null, false).kind, null);
  // SNX 2026-11-02 noise: 0.5 ATR UNDER the entry, under the zone, above SL -> nothing (not "touched")
  const snx: Setup = { ...S, ticker: 'SNX', src: 'own', entry: 236.61, stop: 218.8, target: 282.57, rr: 2.58, zoneTop: 242.01, zoneBottom: 236.56, atr: 21.81, starred: true };
  assertEquals(decide(snx, { price: 225.65, dayHigh: 237.44, dayLow: 225.05, prevClose: 236 }, null, false).kind, null);
  // under SL: cancel only when an order may be working (alert sent) or starred
  assertEquals(decide(S, { price: 69.9, dayHigh: 71, dayLow: 69.5, prevClose: 71 }, null, false).kind, null);
  assertEquals(decide(S, { price: 69.9, dayHigh: 71, dayLow: 69.5, prevClose: 71 }, null, true).kind, 'cancel');
  assertEquals(decide({ ...S, starred: true }, { price: 69.9, dayHigh: 71, dayLow: 69.5, prevClose: 71 }, null, false).kind, 'cancel');
});

Deno.test('cooldown across days, hadOrder, shares, earnings block', () => {
  const r = [{ kind: 'limit', entry: 75.79, stop: 70.1, target: 95.44, trade_day: '2026-11-02' }];
  assert(coolingDown('limit', S, r, '2026-11-05'));
  assert(!coolingDown('limit', S, r, '2026-11-09'));                       // 7 days later
  assert(!coolingDown('limit', { ...S, stop: 71 }, r, '2026-11-03'));      // levels changed -> new suggestion
  assert(!coolingDown('triggered', S, r, '2026-11-03'));
  assert(hadOrder(S, r) && !hadOrder({ ...S, entry: 80 }, r));
  assertEquals(shares(S), 9);
  assertEquals(earningsBlock({ n: '2026-11-05' }, '2026-11-02'), 'דוחות בעוד 3 ימים (2026-11-05)');
  assertEquals(earningsBlock({ n: '2027-01-27', p: [{ d: '2026-10-23', t: 'amc' }] }, '2026-11-02'), 'שבוע דוחות (2026-10-23)'); // reacts Mon 10/26
  assertEquals(earningsBlock({ n: '2027-01-27', p: [{ d: '2026-10-21', t: 'amc' }] }, '2026-11-02'), null);
});

Deno.test('Hebrew messages', () => {
  const m = message('limit', S, { price: 77.5, dayHigh: 78, dayLow: 77, prevClose: 78 }, { kind: 'limit', why: '', distAtr: 0.3 });
  assert(m.startsWith('📌 DAL — שווה לשים פקודה 🔥 רשימה חמה'));
  assert(m.includes('לימיט קנייה ב-75.79') && m.includes('9 מניות') && m.includes('(מומחים)') && m.endsWith('#/t/DAL'));
  const b = message('limit', S, { price: 75, dayHigh: 76, dayLow: 74.8, prevClose: 75.5 }, { kind: 'limit', why: '', distAtr: -0.14 });
  assert(b.includes('Buy-Stop ב-75.79'));
  assert(message('triggered', S, { price: 76.5, dayHigh: 77, dayLow: 75.5, prevClose: 77 }, { kind: 'triggered', why: '', distAtr: 0.12 }).includes('הכניסה הופעלה'));
  assert(message('cancel', S, { price: 69.9, dayHigh: 71, dayLow: 69.5, prevClose: 71 }, { kind: 'cancel', why: '', distAtr: -1 }).includes('ירד מתחת ל-SL 70.10'));
});

Deno.test('falling knife (Eyal 2026-11-09): healthy red loud last week -> no limit / triggered; cancel unchanged', () => {
  const K = { ...S, knife: true };
  const near = { price: 76.9, dayHigh: 78, dayLow: 76.5, prevClose: 78 };
  assertEquals(decide(S, near, null, false).kind, 'limit');
  const d = decide(K, near, null, false);
  assertEquals(d.kind, null); assert(d.why.includes('נר אדום בריא'));
  assertEquals(decide(K, { price: 76.5, dayHigh: 77, dayLow: 75.5, prevClose: 77 }, null, false).kind, null);   // would be triggered
  assertEquals(decide(K, { price: 69.9, dayHigh: 71, dayLow: 69.5, prevClose: 71 }, null, true).kind, 'cancel');  // price <= SL, order working
  assertEquals(buildSetup('DAL', [], Z, { ...O, knife: true })!.knife, true);
});
