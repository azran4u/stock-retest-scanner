// TS Fib anchor + weekly-sampled SMA (src/indicators.ts) vs the Python export (srs_app/fib.py -> app/data/index.json fib_*,
// spark.json ma) on every exported ticker. Usage: node test_fib.mjs  (exits 1 on any mismatch)
import { buildSync } from 'esbuild';
import { readFileSync, mkdtempSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const dir = mkdtempSync(join(tmpdir(), 'fib-'));
const out = join(dir, 'ind.mjs');
buildSync({ entryPoints: [new URL('./src/indicators.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node' });
const { fibAnchor, fibConfluence, smaWeekly } = await import(out);
const data = new URL('../app/data/', import.meta.url).pathname;
const idx = JSON.parse(readFileSync(data + 'index.json'));
const spark = JSON.parse(readFileSync(data + 'spark.json'));
let n = 0, bad = 0, smaOk = 0;
for (const r of idx.rows) {
  const f = data + 'candles/' + r.ticker + '.json';
  if (!existsSync(f)) continue;
  const daily = JSON.parse(readFileSync(f)).d.map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
  const a = fibAnchor(daily); n++;
  const same = (!a && r.fib_low == null) || (a && a.low === r.fib_low && a.high === r.fib_high && a.low_date === r.fib_low_date && a.high_date === r.fib_high_date
    && Math.abs(a.atr_w - r.fib_atr) < 1e-3);
  let conf = true;
  if (a) {
    const c = fibConfluence(a, a.atr_w, r.current_price, r.tv_zone_top, r.tv_zone_bottom);
    conf = c.priceLevel === r.fib_price_level && JSON.stringify(c.zoneLevels) === JSON.stringify(r.fib_zone_levels || []);
  }
  if (!same || !conf) { bad++; console.log('FAIL', r.ticker, 'py', r.fib_low, r.fib_low_date, r.fib_high, r.fib_high_date, r.fib_price_level, r.fib_zone_levels, 'ts', a && [a.low, a.low_date, a.high, a.high_date]); }
  // SMA200 at the last week vs the quantized export (1/254 of the range)
  const sp = spark[r.ticker];
  if (sp?.ma) {
    const q = Buffer.from(sp.ma.q, 'base64'), k = (sp.ma.hi - sp.ma.lo) / 254, last = q[q.length - 1];
    const ts = smaWeekly(daily, 200).at(-1)?.value;
    if (last !== 255 && ts != null && Math.abs(sp.ma.lo + last * k - ts) <= k * 0.51 + 0.01) smaOk++;
    else if (last !== 255) { bad++; console.log('FAIL sma200', r.ticker, sp.ma.lo + last * k, ts); }
  }
}
console.log(`${n - bad}/${n} fib anchors + confluence agree (TS vs Python); SMA200 last week agrees on ${smaOk}`);
if (bad || !n) process.exitCode = 1;
