// Lives archive filter / sort / date fallback (src/lives.ts). Usage: node test_lives.mjs
import { buildSync } from 'esbuild';
import { mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const out = join(mkdtempSync(join(tmpdir(), 'lv-')), 'l.mjs');
buildSync({ entryPoints: [new URL('./src/lives.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node' });
const L = await import(out);
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

const rows = L.normalizeLives([
  { youtube_id: 'aaaaaaaaaaa', link: 'https://youtu.be/aaaaaaaaaaa', archive: 'community', live_date: '', post_date: '2024-01-05', post_time: '09:40', mentor: '', title: 'הקלטת לייב', summary_link: '', stocks: '' },
  { youtube_id: 'bbbbbbbbbbb', link: 'https://youtu.be/bbbbbbbbbbb', archive: 'students', live_date: '2026-11-18', post_date: '2026-11-18', post_time: '17:27', mentor: 'רז', title: 'לייב עם רז 18.11.26', summary_link: 'https://cyclestrading.com/magazine/lives/go/raz-18-11', stocks: 'AAPL SNDK' },
  { youtube_id: 'ccccccccccc', link: 'https://youtu.be/ccccccccccc', archive: 'students', live_date: '2026-11-16', post_date: '2026-11-17', post_time: '12:52', mentor: 'יוסף', title: 'לייב עם יוסף 16.11.26', summary_link: 'https://cyclestrading.com/magazine/lives/go/yosef-16-11', stocks: 'SPG STT NVDA WM' },
  { youtube_id: 'aaaaaaaaaaa', link: 'https://youtu.be/aaaaaaaaaaa', archive: 'community', post_date: '2024-01-06', mentor: 'זיו', title: 'duplicate should drop' },
]);
ok(rows.length === 3, `dedupe by youtube_id -> 3 (got ${rows.length})`);
const old = rows.find((r) => r.youtube_id === 'aaaaaaaaaaa');
ok(old.display_date === '2024-01-05' && old.mentor === 'לא צוין', 'blank live_date falls back to post_date; blank mentor = לא צוין');
ok(L.formatLiveDate('2026-11-18') === '18.11.2026', 'Hebrew date format');

const f = { q: '', mentor: '', archive: '', hasSummary: '', sort: 'date' };
const byDate = L.filterLives(rows, f);
ok(byDate[0].youtube_id === 'bbbbbbbbbbb' && byDate[1].youtube_id === 'ccccccccccc' && byDate[2].youtube_id === 'aaaaaaaaaaa', 'default sort: newest display_date first');
ok(L.displayDateOf({ live_date: '2026-11-16', post_date: '2026-11-17' }) === '2026-11-16', 'display date prefers live_date over post_date');

const byMentor = L.filterLives(rows, { ...f, sort: 'mentor' });
ok(byMentor.map((r) => r.mentor).join(',') === 'יוסף,לא צוין,רז', `sort by mentor he-IL (${byMentor.map((r) => r.mentor).join(',')})`);

ok(L.filterLives(rows, { ...f, q: 'רז' }).length === 1 && L.filterLives(rows, { ...f, q: 'רז' })[0].mentor === 'רז', 'search mentor');
ok(L.filterLives(rows, { ...f, q: 'aapl' }).map((r) => r.youtube_id).join() === 'bbbbbbbbbbb', 'search ticker case-insensitive');
ok(L.filterLives(rows, { ...f, q: 'יוסף 16' }).length === 1, 'search title');
ok(L.filterLives(rows, { ...f, mentor: 'רז' }).length === 1, 'filter mentor');
ok(L.filterLives(rows, { ...f, archive: 'community' }).every((r) => r.archive === 'community') && L.filterLives(rows, { ...f, archive: 'community' }).length === 1, 'filter archive');
ok(L.filterLives(rows, { ...f, hasSummary: 'yes' }).length === 2 && L.filterLives(rows, { ...f, hasSummary: 'no' }).length === 1, 'filter has-summary');
ok(L.filterLives(rows, { ...f, q: 'NVDA', mentor: 'יוסף', archive: 'students', hasSummary: 'yes' }).length === 1, 'AND search+filters');
ok(L.filterLives(rows, { ...f, q: 'no-such' }).length === 0, 'no match');
ok(L.mentorsOf(rows).join(',') === 'יוסף,לא צוין,רז', 'mentorsOf sorted he');

const html = L.livesTableHtml(byDate) + L.livesToolbarHtml(f, 3, 3, L.mentorsOf(rows));
ok(html.includes('לייב עם רז') && html.includes('הקלטה') && html.includes('סיכום') && html.includes('AAPL'), 'table has title, links, stocks');
ok(html.includes('dir="rtl"') === false, 'toolbar does not force a nested rtl (page already rtl)'); // weak check, just shouldn't break
ok(html.includes('id="lvMentor"') && html.includes('id="lvArchive"') && html.includes('id="lvSum"') && html.includes('id="lvSort"') && html.includes('id="lvQ"'), 'all filter controls present');
ok(!html.includes('lives.json') && !html.includes('/app/'), 'html does not point at a public static json');

if (process.exitCode) console.log('FAILED'); else console.log('all ok');
