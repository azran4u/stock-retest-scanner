// Stock overview 'סקירה' (Eyal 2026-10-24: short Hebrew overview for every PASS stock). Demo mode with an injected
// ticker_research row (CSCO, not starred): section shown with bold topic heads + source links + update date;
// no section for a ticker without a row; open/closed state persisted across reload; desktop + iPhone screenshots.
// Usage: node e2e_research.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/research_shots';
mkdirSync(OUT, { recursive: true });
const RES = JSON.parse(readFileSync(new URL('./e2e_research.fixture.json', import.meta.url)));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
for (const [name, vp, mobile] of [['desktop_1440', { width: 1440, height: 900 }, false], ['iphone_390', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  await ctx.addInitScript((r) => { window.__demoResearch = r; }, RES);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/t/CSCO');
  await page.waitForSelector('#research', { timeout: 15000 });
  const info = await page.evaluate(() => {
    const d = document.querySelector('#research');
    return { open: d.open, heads: [...d.querySelectorAll('.rs-body p > b')].map((b) => b.textContent), paras: d.querySelectorAll('.rs-body p').length,
      links: d.querySelectorAll('.rs-src a').length, date: d.querySelector('summary .muted').textContent, starred: document.querySelector('#star').textContent };
  });
  ok(info.open, `${name}: CSCO overview shown, open by default`);
  ok(info.starred === '☆', `${name}: shown although CSCO is not starred`);
  ok(info.paras === RES[0].summary_he.split('\n').length, `${name}: one paragraph per line (${info.paras})`);
  ok(['תחום:', 'דוח אחרון:', 'אנליסטים:', 'חדשות:', 'דוח הבא:'].every((h) => info.heads.includes(h)), `${name}: bold topic heads ${info.heads.join(' | ')}`);
  ok(info.links === RES[0].sources.length, `${name}: ${info.links} source links`);
  ok(/24\.10\.26|25\.10\.26/.test(info.date), `${name}: update date in Israel time (${info.date})`);
  await page.locator('#research').screenshot({ path: `${OUT}/${name}_research.png` });
  await page.screenshot({ path: `${OUT}/${name}_page.png`, fullPage: false });
  // collapse -> persisted
  await page.click('#research > summary');
  await page.waitForTimeout(200);
  await page.reload(); await page.waitForSelector('#research');
  ok(!(await page.evaluate(() => document.querySelector('#research').open)), `${name}: closed state persisted after reload`);
  await page.click('#research > summary');
  // ticker without a row -> no section
  await page.goto(BASE + '?demo=1#/t/TSM'); await page.waitForSelector('#panel section'); await page.waitForTimeout(300);
  ok(!(await page.$('#research')), `${name}: no overview section for a ticker without a row`);
  await ctx.close();
}
ok(errors.length === 0, `no page errors ${errors.join(' | ')}`);
await browser.close();
