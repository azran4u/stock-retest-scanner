// Weinstein stages page (#/stages, Eyal 2026-11-13): demo mode at desktop 1280x900 and phone 390x844.
// Header link opens it, market + sector strength shown, tabs (2A / 1-4 / no volume) filter by stage, cards carry the
// stage checks, charts draw, search + sort work, no horizontal overflow, back returns to the list.
// Usage: node e2e_stages.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/stages_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
for (const [name, vp, mobile] of [['desktop', { width: 1280, height: 900 }, false], ['mobile', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage(); const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1'); await page.evaluate(() => localStorage.removeItem('srs-stages-ui'));
  await page.waitForSelector('#stagesLink'); await page.waitForTimeout(400);
  await page.click('#stagesLink'); await page.waitForSelector('.stcard');
  ok(page.url().includes('#/stages'), `${name}: link opens #/stages`);
  ok(await page.locator('.mkts .mk').count() === 3, `${name}: SPY / QQQ / IWM stage shown`);
  const n2a = await page.locator('.stcard').count();
  const badges = await page.$$eval('.stcard .r1 .badge.st', (b) => b.map((x) => x.textContent));
  ok(n2a > 0 && badges.every((t) => t.includes('2A')), `${name}: 2A tab = ${n2a} new stage-2 breakouts`);
  await page.waitForTimeout(500);
  ok(await page.$$eval('canvas.stchart', (c) => c.slice(0, 2).every((x) => x.dataset.drawn === '1')), `${name}: charts drawn`);
  await page.screenshot({ path: `${OUT}/${name}_2a.png` });
  for (const s of ['1', '2', '3', '4']) {
    await page.click(`[data-tab="${s}"]`); await page.waitForTimeout(150);
    const b = await page.$$eval('.stcard .r1 .badge.st', (x) => x.map((e) => e.className));
    ok(b.length > 0 && b.every((c) => c.includes('st' + s)), `${name}: tab stage ${s} (${b.length} cards shown)`);
  }
  await page.click('.stcard .stchk summary'); await page.waitForTimeout(100);
  ok(await page.locator('.stcard .stchk[open] .cks li').count() >= 9, `${name}: card checks expand`);
  await page.screenshot({ path: `${OUT}/${name}_s4.png` });
  await page.click('[data-tab="2A"]'); await page.waitForTimeout(150);
  const first = await page.$eval('.stcard .sttk b', (e) => e.textContent);
  await page.fill('#stq', first); await page.waitForTimeout(600);
  ok(await page.locator('.stcard').count() >= 1 && (await page.$eval('.stcard .sttk b', (e) => e.textContent)) === first, `${name}: search ${first}`);
  await page.fill('#stq', ''); await page.waitForTimeout(600);
  await page.selectOption('#stsort', 'vol'); await page.waitForTimeout(200);
  const vols = await page.$$eval('.stcard', (cs) => cs.map((c) => parseFloat([...c.querySelectorAll('.skv')].find((k) => k.textContent.includes('מחזור פריצה'))?.querySelector('b')?.textContent || 'NaN')));
  ok(vols.length > 1 && vols.every((v, i) => i === 0 || v <= vols[i - 1]), `${name}: sort by breakout volume`);
  ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow`);
  await page.click('.strulesbox summary'); await page.waitForTimeout(100);
  ok((await page.locator('.strules').innerText()).includes('Mansfield'), `${name}: rules shown`);
  await page.click('#back'); await page.waitForTimeout(400);
  ok(!page.url().includes('#/stages'), `${name}: back leaves the page`);
  ok(!errors.length, `${name}: no page errors ${errors.join(' | ')}`);
  await ctx.close();
}
await browser.close();
