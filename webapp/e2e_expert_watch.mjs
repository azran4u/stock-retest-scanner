// Expert watchlist (Eyal 2026-11-01): builtin list 'רשימת מעקב מומחים' = app/data/expert_watch.json (nightly), ranked,
// two tiers ('מוכנה' / 'ממתינה לאישור'), criteria box, one Hebrew reason line per stock. iPhone 390 + laptop 1366.
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/expert_watch';
mkdirSync(OUT, { recursive: true });
const W = JSON.parse(readFileSync(new URL('../app/data/expert_watch.json', import.meta.url)));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.evaluate(() => localStorage.removeItem('srs-app-v1')); await page.reload(); await page.waitForSelector('.row');
  await page.waitForFunction(() => window.__srs.expertWatch != null); await page.waitForTimeout(300);
  const opt = await page.locator('#listSel option[value="expertwatch"]').textContent();
  ok(opt.includes('רשימת מעקב מומחים'), `${name}: builtin list in the list picker`);
  await page.locator('#listSel').selectOption('expertwatch'); await page.waitForTimeout(400);
  const have = await page.evaluate(() => window.__srs.S.rows.map((r) => r.ticker).concat([...window.__srs.S.watch.keys()]));
  const want = W.items.filter((x) => have.includes(x.t)).map((x) => x.t);
  const shown = await page.$$eval('.list .row', (els) => els.map((e) => e.dataset.t));
  ok(want.length > 0 && JSON.stringify(shown) === JSON.stringify(want), `${name}: ${shown.length} stocks in rank order (${shown.slice(0, 5).join(' ')}…)`);
  const head = await page.locator('#ewHead').textContent();
  ok(head.includes('R:R מומחים ≥ 2') && head.includes('מוכנה') && head.includes('ממתינה לאישור'), `${name}: criteria box`);
  const tiers = await page.$$eval('.list .ewtier', (els) => els.map((e) => e.dataset.tier));
  const nReady = W.items.filter((x) => x.tier === 'מוכנה' && have.includes(x.t)).length;
  ok(JSON.stringify(tiers) === JSON.stringify([nReady ? 'ready' : null, nReady < want.length ? 'wait' : null].filter(Boolean)), `${name}: tier headers ${tiers.join(' / ')}`);
  const first = W.items.find((x) => x.t === want[0]);
  const line = await page.locator(`.row[data-t="${first.t}"] .ewl`).textContent();
  ok(line.includes(first.reason_he) && line.includes(`#${first.rank}`), `${name}: reason line '${line.trim().slice(0, 70)}…'`);
  await page.screenshot({ path: `${OUT}/${name}_list_top.png` });
  const wait1 = W.items.find((x) => x.tier !== 'מוכנה' && have.includes(x.t));
  if (wait1) { await page.locator('.ewtier[data-tier="wait"]').scrollIntoViewIfNeeded(); await page.waitForTimeout(200); await page.screenshot({ path: `${OUT}/${name}_list_waiting.png` }); }
  await page.reload(); await page.waitForSelector('.row'); await page.waitForFunction(() => window.__srs.expertWatch != null); await page.waitForTimeout(300);
  const again = await page.$$eval('.list .row', (els) => els.map((e) => e.dataset.t));
  ok(JSON.stringify(again) === JSON.stringify(want), `${name}: list selection persisted`);
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
