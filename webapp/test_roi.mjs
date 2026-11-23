// Roi analysis helpers (src/roi.ts). Usage: node test_roi.mjs
import { buildSync } from 'esbuild';
import { mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const out = join(mkdtempSync(join(tmpdir(), 'roi-')), 'r.mjs');
buildSync({ entryPoints: [new URL('./src/roi.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node' });
const R = await import(out);
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

ok(R.recKeyOf('כניסה עכשיו / להציב פקודת לימיט') === 'enter', 'parse enter');
ok(R.recKeyOf('לחכות לאישור (מה הטריגר)') === 'wait', 'parse wait');
ok(R.recKeyOf('לדלג (למה)') === 'skip', 'parse skip');
ok(R.recKeyOf('enter') === 'enter' && R.recKeyOf('') == null && R.recKeyOf('something else') == null, 'parse edge cases');

const rows = R.normalizeRoiList([
  { ticker: 'aal', recommendation: 'כניסה עכשיו / להציב פקודת לימיט', entry: 11.9, stop: 10.7, target: 18.8, rr: 5.67, rationale_he: 'נימוק', checklist: [{ item: 'מגמה', result: '✔', detail: 'עולה' }, { item: 'אישור', result: '✖', detail: 'אין' }], roi_mentions: [{ date: '2026-10-01', source: 'לייב', quote: 'נראית חיובית' }], as_of: '2026-11-23' },
  { ticker: 'AAL', recommendation: 'לדלג (למה)', rr: 1 }, // dup, dropped
  { ticker: 'NOW', recommendation: 'לחכות לאישור (מה הטריגר)', rr: 3.2, rationale_he: 'לחכות', checklist: [], roi_mentions: [], as_of: '2026-11-23' },
  { ticker: '', recommendation: 'כניסה עכשיו' },
  { ticker: 'XX', recommendation: 'לא ידוע' },
]);
ok(rows.length === 2 && rows[0].ticker === 'AAL' && rows[0].rec_key === 'enter', `normalize dedupe/case (${rows.length}, ${rows[0]?.ticker})`);
ok(rows[1].ticker === 'NOW' && rows[1].rec_key === 'wait', 'second row wait');

const badge = R.roiBadgeHtml(rows[0]);
ok(badge.includes('כניסה עכשיו') && badge.includes('5.67') && badge.includes('b-roi-enter') && badge.includes('רועי R:R'), 'badge has rec + Roi R:R');
ok(R.roiBadgeHtml(null) === '' && R.roiBadgeHtml(undefined) === '', 'no data -> no badge');

const panel = R.roiPanelHtml(rows[0]);
ok(panel.includes('ניתוח רועי') && panel.includes('שיטת רועי') && panel.includes('נימוק') && panel.includes('כניסה') && panel.includes('סטופ') && panel.includes('יעד') && panel.includes('מגמה') && panel.includes('נראית חיובית') && panel.includes('01.10.2026') && panel.includes('לא משנים את סטטוס PASS'), 'panel has checklist, rationale, levels, quote, disclaimer');
ok(R.roiPanelHtml(null) === '', 'no data -> no panel');
ok(!panel.includes('pass_analysis.json') && !panel.includes('/app/'), 'html does not point at a public static json');

if (process.exitCode) console.log('FAILED'); else console.log('all ok');
