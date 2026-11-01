// Filter 'פטישים על אזור המומחים' (Eyal 2026-11-01): >= N hammer weeks (H textbook / h near-hammer) touching the expert
// zone in the last X completed weeks (defaults N=2, X=6, both persisted) and no weekly close under the zone in that window.
// Combines with the distance filter. Stock page lists the hammer weeks; weekly chart marks them. iPhone 390 + laptop 1366.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/expert_hammers';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.evaluate(() => localStorage.removeItem('srs-app-v1')); await page.reload(); await page.waitForSelector('.row');
  await page.waitForFunction(() => window.__srs.expertDoc != null); await page.waitForTimeout(300);
  const want = (N, X, near) => page.evaluate(({ N, X, near }) => { const { S, factsOf, expertDoc, expertDistOf } = window.__srs;
    return S.rows.filter((r) => !factsOf(r).unfit).filter((r) => { const e = expertDoc.tickers[r.ticker]; if (!e?.ok) return false;
      const n = (e.hammers || []).filter((h) => h.k <= X).length, b = (e.closes_below_k || []).some((k) => k <= X);
      const d = expertDistOf(r.ticker); return n >= N && !b && (near == null || (d && d.atr <= near)); }).map((r) => r.ticker).sort(); }, { N, X, near });
  const shown = async () => (await page.$$eval('.row', (els) => els.map((e) => e.dataset.t))).sort();
  await page.locator('#ftog').click();
  const fi = page.locator('.fi[data-f="expertham"]');
  ok((await fi.textContent()).includes('פטישים על אזור המומחים') && await fi.locator('.fx').inputValue() === '2' && await fi.locator('.fx2').inputValue() === '6', `${name}: filter listed, defaults N=2 X=6`);
  await fi.locator('input[type=checkbox]').click(); await page.waitForTimeout(300);
  let w = await want(2, 6), got = await shown();
  ok(w.length > 0 && JSON.stringify(got) === JSON.stringify(w), `${name}: default -> ${w.length}: ${w.join(' ')}`);
  await fi.locator('.fx').fill('1'); await fi.locator('.fx2').fill('4'); await page.waitForTimeout(300);
  w = await want(1, 4); got = await shown();
  ok(JSON.stringify(got) === JSON.stringify(w), `${name}: N=1 X=4 -> ${w.length}`);
  await fi.locator('.fx').fill('2'); await fi.locator('.fx2').fill('6'); await page.waitForTimeout(300);
  const fn = page.locator('.fi[data-f="expertnear"]');
  await fn.locator('input[type=checkbox]').click(); await page.waitForTimeout(300);
  w = await want(2, 6, 1); got = await shown();
  ok(JSON.stringify(got) === JSON.stringify(w), `${name}: + distance ≤ 1 ATR -> ${w.length}: ${w.join(' ')}`);
  await fn.locator('input[type=checkbox]').click(); await page.waitForTimeout(300);
  if (!mobile) await page.locator('#ftog').click();
  await page.screenshot({ path: `${OUT}/${name}_list_default.png` });
  await page.reload(); await page.waitForSelector('.row'); await page.waitForFunction(() => window.__srs.expertDoc != null); await page.waitForTimeout(300);
  const ui = await page.evaluate(() => JSON.parse(localStorage.getItem('srs-app-v1') || '{}'));
  ok(ui.f?.expertham?.on === true && +ui.f.expertham.x === 2 && +ui.f.expertham.y === 6 && JSON.stringify(await shown()) === JSON.stringify(await want(2, 6)), `${name}: filter + N + X persisted`);
  // stock page + weekly chart marks
  const t = (await want(2, 6)).includes('ASB') ? 'ASB' : (await want(2, 6))[0];
  const e = await page.evaluate((t) => window.__srs.expertDoc.tickers[t], t);
  await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(500);
  await page.locator('[data-tf="W"]').click(); await page.waitForTimeout(500);
  const marks = await page.evaluate(() => [...document.querySelectorAll('#chart g.experthammers text')].map((x) => x.textContent));
  ok(marks.length > 0 && marks.length <= e.hammers.length && marks.every((m) => m === 'H' || m === 'h'), `${name} ${t}: weekly chart marks ${marks.join('')} (${e.hammers.length} stored)`);
  await page.screenshot({ path: `${OUT}/${name}_${t}_weekly.png` });
  const ham = await page.locator('#secExpert .exham').getAttribute('data-ham');
  ok(ham === e.hammers.map((h) => h.w + ':' + h.s).join(','), `${name} ${t}: stock page lists ${ham}`);
  await page.locator('#secExpert .exham').scrollIntoViewIfNeeded(); await page.waitForTimeout(150);
  await page.screenshot({ path: `${OUT}/${name}_${t}_panel.png` });
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
