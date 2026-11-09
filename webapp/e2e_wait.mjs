// Falling knife (Eyal 2026-11-09): a healthy red last week on above-average volume blocks PASS again (it was info only
// 2026-10-26 .. 2026-11-09): no PASS badge, 'FAIL · נר אדום בריא במחזור גבוה — ממתינים לסגירת השבוע הבא' + the
// 'שבוע אדום במחזור גבוה' badge + reason line, stock-page box; the 'אין שבוע אדום עם מחזור גבוה' filter hides them.
// Desktop + mobile (same content). Demo mode. Usage: node e2e_wait.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const texts = {};
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
for (const [name, opt] of [['mobile', { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true }], ['desktop', { viewport: { width: 1366, height: 900 } }]]) {
const ctx = await browser.newContext({ ...opt, locale: 'he-IL' });
console.log('--', name);
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto(BASE + '?demo=1');
await page.waitForSelector('.row');
await page.evaluate(() => window.__srs.setChip('pass')); await page.waitForTimeout(300);
const passBefore = await page.locator('.row .b-pass').count();
ok(passBefore > 0, `demo PASS rows: ${passBefore}`);
ok(await page.locator('.fi[data-f="st_wait"]').count() === 0 && await page.locator('.b-wait:text("ממתינה לסגירה")').count() === 0, 'no WAIT filter / badge');
await page.route('**/data/index.json*', async (route) => {
  const res = await route.fetch(); const j = await res.json();
  for (const r of (j.rows || j)) { r.f_no_red_vol_week = false; r.red_vol_week_date = '2026-10-23'; r.red_vol_ratio = 1.4; r.red_vol_body_pct = 60; }
  await route.fulfill({ response: res, json: j });
});
await page.reload(); await page.waitForSelector('.list');
await page.evaluate(() => window.__srs.setChip('all')); await page.waitForSelector('.row'); await page.waitForTimeout(300);
ok(await page.locator('.row .b-pass').count() === 0, `red loud week = no PASS (was ${passBefore})`);
ok(await page.locator('.row .badge:text("נר אדום בריא במחזור גבוה — ממתינים לסגירת השבוע הבא")').count() > 0, 'FAIL reason badge on the rows');
ok(await page.locator('.row .b-wait:text("שבוע אדום במחזור גבוה")').count() >= passBefore, 'badge on the rows');
const why = await page.locator('.row .wait-why').first().textContent();
ok(/נר אדום 23\/10 .*מחזור 1\.40× ממוצע 30 יום/.test(why || ''), `reason line: ${why}`);
await page.evaluate((k) => { const u = JSON.parse(localStorage.getItem('srs-app-v1') || '{}'); u.f = { ...(u.f || {}), [k]: { on: true } }; localStorage.setItem('srs-app-v1', JSON.stringify(u)); }, 'noRedVol');
await page.reload(); await page.waitForSelector('.list');
ok(await page.locator('.row').count() === 0, "filter 'אין שבוע אדום עם מחזור גבוה' hides them");
await page.evaluate((k) => { const u = JSON.parse(localStorage.getItem('srs-app-v1') || '{}'); u.f = { ...(u.f || {}), [k]: { on: false } }; localStorage.setItem('srs-app-v1', JSON.stringify(u)); }, 'noRedVol');
await page.reload(); await page.waitForSelector('.list');
await page.evaluate(() => window.__srs.setChip('all')); await page.waitForSelector('.row'); await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/20_knife_list_${name}.png` });
await page.locator('.row:has(.badge:text("נר אדום בריא במחזור גבוה — ממתינים לסגירת השבוע הבא"))').first().click();
await page.waitForSelector('.wait-box', { timeout: 15000 });
const box = await page.locator('.wait-box[data-knife="1"]').textContent();
ok(/לא ב-PASS/.test(box || '') && /סכין נופלת/.test(box || '') && /השבוע הבא/.test(box || ''), 'stock page: falling-knife box');
ok(!/מידע בלבד/.test(await page.locator('.wait-box').first().textContent()), 'no "info only" wording');
await page.screenshot({ path: `${OUT}/21_knife_ticker_${name}.png`, fullPage: true });
texts[name] = box;
await ctx.close();
ok(errors.length === 0, `no page errors ${JSON.stringify(errors)}`);
}
ok(texts.mobile === texts.desktop, 'mobile box text = desktop box text');
await browser.close();
