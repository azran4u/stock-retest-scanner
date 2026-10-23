// TS bot-Long rule (src/botlong.ts) vs the Python rule (srs_app.bot_drawings.long_from_zone) on the golden cases.
// Usage: node test_botlong.mjs   (bundles src/botlong.ts with esbuild; exits 1 on any mismatch > 0.01)
import { buildSync } from 'esbuild';
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const dir = mkdtempSync(join(tmpdir(), 'botlong-'));
const out = join(dir, 'botlong.mjs');
buildSync({ entryPoints: [new URL('./src/botlong.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node' });
const { botLongFromZone } = await import(out);
const g = JSON.parse(gunzipSync(readFileSync(new URL('../tests/golden/zone_long_golden.json.gz', import.meta.url))).toString());
let bad = 0;
for (const c of g.cases) {
  const daily = g.daily[c.ticker].map(([time, open, high, low, close, volume]) => ({ time, open, high, low, close, volume }));
  const r = botLongFromZone(daily, c.zone_bottom, c.zone_top);
  const ok = r && Math.abs(r.entry - c.entry) <= 0.011 && Math.abs(r.stop - c.stop) <= 0.011 && r.sl_src === c.sl_src;
  if (!ok) { bad++; console.log('FAIL', c.ticker, c.variant, 'py', c.entry, c.stop, c.sl_src, 'ts', r && r.entry, r && r.stop, r && r.sl_src); }
}
console.log(`${g.cases.length - bad}/${g.cases.length} golden cases agree (TS vs Python)`);
if (bad) process.exitCode = 1;
