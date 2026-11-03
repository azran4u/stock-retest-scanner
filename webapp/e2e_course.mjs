// Experts-method course page (#/course, Eyal 2026-11-03): demo mode at desktop 1280x900 and phone 390x844.
// The header link opens it, all charts load, the TOC opens + scrolls to a module (data-goto, not #anchors), no
// horizontal overflow, back returns to the list. Usage: node e2e_course.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/course/shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
for (const [name, vp, mobile] of [['desktop', { width: 1280, height: 900 }, false], ['mobile', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage(); const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1'); await page.waitForSelector('#courseLink'); await page.waitForTimeout(500);
  await page.click('#courseLink'); await page.waitForSelector('.course details.mod');
  ok(page.url().includes('#/course'), `${name}: link opens #/course`);
  ok(await page.locator('.course details.mod').count() === 11, `${name}: 11 modules`);
  await page.evaluate(() => document.querySelectorAll('.course details.mod').forEach((d) => (d.open = true)));
  await page.waitForTimeout(600);
  const imgs = await page.evaluate(() => [...document.querySelectorAll('.course img')].map((i) => i.complete && i.naturalWidth > 0));
  ok(imgs.length >= 12 && imgs.every(Boolean), `${name}: ${imgs.length} charts loaded`);
  ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow`);
  await page.evaluate(() => document.querySelectorAll('.course details.mod').forEach((d) => (d.open = d.id === 'm0')));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${OUT}/${name}_top.png` });
  await page.click('.toc [data-goto="m3"]'); await page.waitForTimeout(900);
  const m3 = await page.evaluate(() => { const d = document.getElementById('m3'); const r = d.getBoundingClientRect(); return { open: d.open, top: Math.round(r.top) }; });
  ok(m3.open && m3.top >= 0 && m3.top < 200 && page.url().includes('#/course'), `${name}: TOC opens + scrolls to module 3 (${JSON.stringify(m3)})`);
  await page.screenshot({ path: `${OUT}/${name}_m3.png` });
  await page.evaluate(() => document.getElementById('m9').open = true);
  await page.evaluate(() => document.getElementById('m9').scrollIntoView()); await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/${name}_m9.png`, fullPage: false });
  await page.click('#back'); await page.waitForTimeout(500);
  ok(!page.url().includes('#/course'), `${name}: back leaves the course`);
  ok(!errors.length, `${name}: no page errors ${errors.join(' | ')}`);
  await ctx.close();
}
await browser.close();
