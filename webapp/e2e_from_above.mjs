// f_from_above (Eyal 2026-10-24, USB): back in the zone from below -> FAIL 'חזרה לאזור מלמטה', demo mode.
// Usage: node e2e_from_above.mjs [baseURL] [outDir]
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
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
await page.goto(BASE + '?demo=1');
await page.waitForSelector('.row');
const row = page.locator('.row', { hasText: 'USB' }).first();
ok(await row.count() === 1, 'USB row listed');
const txt = (await row.textContent()) || '';
ok(/חזרה לאזור מלמטה/.test(txt), 'USB badge: FAIL · חזרה לאזור מלמטה');
ok(await row.locator('.b-pass').count() === 0, 'USB is not PASS');
await row.click();
await page.waitForSelector('.rr-box', { timeout: 15000 });
ok(/מלמעלה/.test(await page.locator('.rr-box').textContent()), 'ticker panel explains: break above, come back from above');
await page.screenshot({ path: `${OUT}/22_from_below_ticker.png`, fullPage: true });
ok(errors.length === 0, `no page errors ${JSON.stringify(errors)}`);
await browser.close();
