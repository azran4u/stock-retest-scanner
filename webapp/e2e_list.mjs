// List mini charts (3y weekly closes) smoke test, demo mode, iPhone 390x844. Usage: node e2e_list.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'he-IL' });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const drawn = () => page.evaluate(() => [...document.querySelectorAll('canvas.spark')].filter((c) => c.dataset.drawn).map((c) => c.dataset.spark));

await page.goto(BASE + '?demo=1');
await page.waitForSelector('.row');
await page.waitForFunction(() => [...document.querySelectorAll('canvas.spark')].some((c) => c.dataset.drawn));
await page.waitForTimeout(300);
const total = await page.locator('canvas.spark').count();
const first = await drawn();
ok(total > 50 && first.length > 0 && first.length < total, `lazy: ${first.length} of ${total} mini charts drawn on first screen`);
const cw = await page.locator('canvas.spark').first().boundingBox();
ok(cw.width > 340 && cw.height >= 110 && cw.height <= 140, `mini chart size ${cw.width.toFixed(0)}x${cw.height.toFixed(0)}`);
// pixels actually painted
const painted = await page.evaluate(() => { const c = document.querySelector('canvas.spark'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++; return n; });
ok(painted > 500, `mini chart painted (${painted} px)`);
const sizes = await page.evaluate(() => performance.getEntriesByType('resource').filter((e) => /spark\.json|candles\//.test(e.name)).map((e) => e.name.split('/').pop()));
ok(sizes.includes('spark.json') && !sizes.some((n) => n.endsWith('.json') && n !== 'spark.json'), `list loads spark.json only, no candle files ${JSON.stringify(sizes)}`);
await page.screenshot({ path: `${OUT}/12_list_sparklines.png` });
console.log('     shot', `${OUT}/12_list_sparklines.png`);
// scroll -> more drawn
await page.evaluate(() => window.scrollTo(0, 4000)); await page.waitForTimeout(400);
ok((await drawn()).length > first.length, 'more mini charts drawn after scrolling');
// chips still work and redraw
await page.evaluate(() => window.scrollTo(0, 0));
await page.click('.chip[data-chip="pass"]'); await page.waitForTimeout(300);
const np = await page.locator('.row').count();
ok(np > 0 && np < total && (await drawn()).length > 0, `PASS chip: ${np} rows, mini charts redrawn`);
// tap row opens chart
const t = await page.locator('.row').first().getAttribute('data-t');
await page.locator('.row canvas.spark').first().tap();
await page.waitForSelector('#chart canvas');
ok((await page.locator('#tk').textContent()) === t, `tapping the mini chart opens ${t}`);
await page.click('#back'); await page.waitForSelector('.row');
await page.waitForFunction(() => [...document.querySelectorAll('canvas.spark')].some((c) => c.dataset.drawn), null, { timeout: 5000 }).catch(() => {});
ok((await drawn()).length > 0, 'mini charts drawn again after returning');
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
