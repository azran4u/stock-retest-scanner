// Inverted-hammer last week (BFH, Eyal 2026-10-24) is information only since 2026-10-26 (WAIT cancelled): every demo
// row's last week is marked an inverted hammer via index.json; the PASS rows stay PASS with the 'פטיש הפוך' info
// badge + reason line, the 'אין פטיש הפוך' filter hides them. Usage: node e2e_inv_hammer.mjs [baseURL]
import { chromium } from 'playwright';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'he-IL' })).newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
await page.goto(BASE + '?demo=1');
await page.waitForSelector('.row');
await page.evaluate(() => window.__srs.setChip('pass')); await page.waitForTimeout(300);
const passBefore = await page.locator('.row .b-pass').count();
ok(passBefore > 0, `demo PASS rows before: ${passBefore}`);
await page.route('**/data/index.json*', async (route) => {
  const res = await route.fetch(); const j = await res.json();
  for (const r of (j.rows || j)) { r.f_no_inv_hammer = false; r.inv_hammer_week_date = '2026-10-23'; }
  await route.fulfill({ response: res, json: j });
});
await page.reload(); await page.waitForSelector('.row');
await page.evaluate(() => window.__srs.setChip('pass')); await page.waitForTimeout(300);
ok(await page.locator('.row .b-pass').count() === passBefore, `inverted hammer = still PASS (${passBefore}, BFH-type)`);
const whys = await page.locator('.row .wait-why').allTextContents();
ok(whys.length >= passBefore && whys.every((w) => /פטיש הפוך 23\/10/.test(w)), `info line: ${whys.length} (${whys[0] || ''})`);
ok(await page.locator('.row .b-wait:text("פטיש הפוך")').count() >= passBefore, 'info badge');
await page.evaluate((k) => { const u = JSON.parse(localStorage.getItem('srs-app-v1') || '{}'); u.f = { ...(u.f || {}), [k]: { on: true } }; localStorage.setItem('srs-app-v1', JSON.stringify(u)); }, 'noInvHammer');
await page.reload(); await page.waitForSelector('.list');
ok(await page.locator('.row').count() === 0, "filter 'אין פטיש הפוך' hides them");
await page.evaluate(() => window.__srs.setChip('pass')); await page.waitForTimeout(300);
await page.locator('.row').first().click();
await page.waitForSelector('.wait-box', { timeout: 15000 });
ok(/פטיש הפוך/.test(await page.locator('.wait-box').first().textContent() || '') && /מידע בלבד/.test(await page.locator('.wait-box').first().textContent() || ''), 'panel explains the inverted hammer (info only)');
ok(errors.length === 0, 'no page errors ' + errors.join(' | '));
await browser.close();
