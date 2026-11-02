// Telegram price-alerts status chip in the list header (public.alert_runs; demo = MemApi stub). iPhone 390 + laptop 1366.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = '/workspace/mobile_shots/price_alerts'; mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch(); const errors = [];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage(); page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.waitForSelector('#alertStat.alstat', { timeout: 10000 });
  const el = page.locator('#alertStat');
  ok((await el.textContent()).includes('התראות') && (await el.getAttribute('title')).includes('בדיקה אחרונה'), `${name}: status chip '${(await el.textContent()).trim()}'`);
  const box = await el.boundingBox(); ok(box && box.x >= 0 && box.x + box.width <= vp.width, `${name}: chip inside the viewport`);
  await page.screenshot({ path: `${OUT}/${name}_header.png`, clip: { x: 0, y: 0, width: vp.width, height: 120 } });
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
