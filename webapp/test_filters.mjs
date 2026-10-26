// Independent list filters, logical AND (src/filters.ts). Usage: node test_filters.mjs  (exits 1 on any failure)
import { buildSync } from 'esbuild';
import { mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const out = join(mkdtempSync(join(tmpdir(), 'flt-')), 'f.mjs');
buildSync({ entryPoints: [new URL('./src/filters.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node' });
const F = await import(out);
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const base = {
  technical: true, rr: 2.5, revD: { hammer: '2026-10-22' }, revW: { engulfing: '2026-10-02', strong_close: '2026-10-23' }, daysToEarn: 20,
  unfit: false, status: 'PASS', needsDrawing: false, review: false, obsolete: false, hammer: false, position: false, starred: false, mine: true,
  commands: false, zoneDist: 0.6, dollarVol: 80e6, history: true, tradable: true, fromAbove: true, noInvHammer: true, noRedVol: true,
  smoothWeeks: 6, sector: 'Technology', instOwn: null, shortFloat: 7, fib: false, today: '2026-10-26',
};
const f = (o) => ({ ...base, ...o });
ok(F.matches(base, {}), 'no filters -> match');
ok(!F.matches(f({ unfit: true }), {}), 'unfit hidden by default');
ok(F.matches(f({ unfit: true }), { unfit: { on: true, mode: 'only' } }) && !F.matches(base, { unfit: { on: true, mode: 'only' } }), 'unfit only');
ok(F.matches(f({ unfit: true }), { unfit: { on: true, mode: 'all' } }) && F.matches(base, { unfit: { on: true, mode: 'all' } }), 'unfit all');
ok(F.matches(base, { rr: { on: true } }) && !F.matches(f({ rr: 1.9 }), { rr: { on: true } }), 'R:R ≥ 2 default');
ok(!F.matches(base, { rr: { on: true, x: 3 } }) && F.matches(base, { rr: { on: false, x: 3 } }), 'R:R param; off = ignored');
ok(!F.matches(f({ rr: null }), { rr: { on: true } }), 'no R:R fails');
ok(F.matches(base, { uptrend: { on: true } }) && !F.matches(f({ technical: null }), { uptrend: { on: true } }), 'uptrend (unknown fails)');
// reversals: daily hammer on 10-22 = within 1 week of 10-26; weekly default kinds hammer+engulfing: engulfing 10-02 = 3.4 weeks
ok(F.matches(base, { revD: { on: true } }), 'daily reversal within 1 week');
ok(!F.matches(base, { revD: { on: true, kinds: ['engulfing'] } }), 'daily reversal kind filter');
ok(!F.matches(base, { revW: { on: true } }) && F.matches(base, { revW: { on: true, x: 4 } }), 'weekly reversal X weeks');
ok(F.matches(base, { revW: { on: true, kinds: ['strong_close'] } }), 'weekly strong close kind');
ok(F.withinWeeks({ hammer: '2026-10-19' }, ['hammer'], 1, '2026-10-26') && !F.withinWeeks({ hammer: '2026-10-18' }, ['hammer'], 1, '2026-10-26'), 'window edge = 7 days');
ok(F.matches(base, { earn: { on: true } }) && !F.matches(f({ daysToEarn: 10 }), { earn: { on: true } }) && !F.matches(f({ daysToEarn: null }), { earn: { on: true } }), 'earnings ≥ 14 (unknown fails)');
ok(F.matches(f({ daysToEarn: 10 }), { earn: { on: true, x: 7 } }), 'earnings param');
// AND
const fs = { rr: { on: true }, uptrend: { on: true }, near: { on: true }, st_pass: { on: true } };
ok(F.matches(base, fs), 'AND all true');
for (const [k, v] of [['rr', 1], ['technical', false], ['zoneDist', 1.5], ['status', 'FAIL']]) ok(!F.matches(f({ [k]: v }), fs), `AND fails when ${k}=${v}`);
ok(!F.matches(f({ status: 'FAIL' }), { st_pass: { on: true } }) && !F.FILTERS.some((d) => d.id === 'st_wait'), 'PASS filter; no WAIT filter (cancelled 2026-10-26)');
ok(F.matches(f({ noInvHammer: false }), { st_pass: { on: true } }) && !F.matches(f({ noInvHammer: false }), { noInvHammer: { on: true } }), 'inverted hammer = info filter only');
ok(F.matches(base, { inst: { on: true } }) && !F.matches(base, { short: { on: true } }) && F.matches(f({ shortFloat: null }), { short: { on: true } }), 'ownership: missing passes, 7% short fails ≤5');
ok(F.matches(base, { sector: { on: true, v: 'Technology' } }) && !F.matches(base, { sector: { on: true, v: 'Energy' } }), 'sector');
ok(F.matches(base, { dvol: { on: true } }) && !F.matches(base, { dvol: { on: true, x: 100 } }), '$vol ≥ X M');
ok(F.matches(base, { smooth: { on: true } }) && !F.matches(base, { smooth: { on: true, x: 8 } }), 'smooth ≥ N');
ok(F.matches(base, { mine: { on: true }, tradable: { on: true }, fromAbove: { on: true }, noInvHammer: { on: true }, noRedVol: { on: true }, history: { on: true } }), 'boolean toggles');
ok(!F.matches(base, { fib: { on: true } }) && !F.matches(base, { starred: { on: true } }), 'fib / starred off');
ok(F.activeCount({}) === 0 && F.activeCount({ rr: { on: true }, unfit: { on: true, mode: 'hide' }, sector: { on: true, v: '' } }) === 1
  && F.activeCount({ unfit: { on: true, mode: 'only' }, earn: { on: true } }) === 2, 'active count');
// Eyal 2026-10-26: no earnings in any source (ETF) passes 'days to earnings'; a known date within 14d still fails
ok(F.matches(f({ daysToEarn: null, earnNone: true }), { earn: { on: true } }), 'no earnings (ETF) passes days-to-earnings');
ok(!F.matches(f({ daysToEarn: 5, earnNone: false }), { earn: { on: true } }), 'known date within 14d still fails');
