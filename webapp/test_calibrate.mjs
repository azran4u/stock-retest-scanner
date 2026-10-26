// Trend calibration page helpers (src/calibrate.ts). Usage: node test_calibrate.mjs (exits 1 on any failure)
import { buildSync } from 'esbuild';
import { mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const out = join(mkdtempSync(join(tmpdir(), 'cal-')), 'c.mjs');
buildSync({ entryPoints: [new URL('./src/calibrate.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node', define: { 'import.meta.env': '{"BASE_URL":"/"}' } });
const C = await import(out);
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const rows = [{ ticker: 'A', group: 'clear_up', bot_view: 'עולה', reason_he: 'שיאים עולים' }, { ticker: 'B', group: 'clear_not', bot_view: 'לא', reason_he: 'דשדוש' },
  { ticker: 'C', group: 'unsure', bot_view: 'לא בטוח', reason_he: 'x' }];
const L = [{ ticker: 'A', label: 'uptrend_mark', value: 'unsure', note: null, asof: '2026-10-25' }, { ticker: 'A', label: 'uptrend_mark', value: 'up', note: 'n', asof: '2026-10-26' },
  { ticker: 'B', label: 'technical', value: 'no', note: null, asof: '2026-10-26' }];
ok(C.latestMarks(L).get('A').value === 'up' && !C.latestMarks(L).has('B'), 'latest mark per ticker, only uptrend_mark');
const p = C.progress(rows, L); ok(p.done === 1 && p.total === 3, 'progress 1/3');
const h = C.calPageHtml(rows, L);
ok(['ברור שבמגמה עולה', 'ברור שלא', 'מתלבט'].every((t) => h.includes(t)) && h.indexOf('ברור שבמגמה עולה') < h.indexOf('ברור שלא') && h.indexOf('ברור שלא') < h.indexOf('מתלבט'), 'three sections in order');
ok(h.includes('דעת הבוט:') && h.includes('שיאים עולים') && !/הצג דעת הבוט/.test(h), 'bot view visible, no hide toggle');
ok(h.includes('סומנו 1/3') && h.includes('href="#/t/A"'), 'progress + ticker links to the stock page');
const e = C.ema([10, 10, 10, 20], 3); ok(Math.abs(e[3] - 15) < 1e-9, 'ema');
