// Copy the TradingView symbol (Eyal 2026-10-27): 📋 next to the ticker on the stock page header and on every list card
// copies 'EXCHANGE:SYMBOL' (export tv_symbol) with a toast 'הועתק: …'; '📋 העתק ל-TV' copies the filtered list as a
// comma-separated list; when the Clipboard API is missing the text is shown selected in a sheet. Desktop + iPhone.
// Usage: node e2e_copy_tv.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const origin = new URL(BASE).origin;
for (const [name, vp, mobile] of [['desktop_1440', { width: 1440, height: 900 }, false], ['iphone_390', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  const click = (sel) => (mobile ? page.locator(sel).first().tap() : page.locator(sel).first().click());
  const clip = () => page.evaluate(() => navigator.clipboard.readText());
  await page.goto(BASE + '?demo=1'); await page.waitForSelector('.row .cpy');
  const idx = await page.evaluate(() => Object.fromEntries(window.__srs.S.rows.map((r) => [r.ticker, r.tv_symbol])));
  const row = await page.locator('.row').first().getAttribute('data-t');
  const want = idx[row];
  ok(/^(NASDAQ|NYSE|AMEX|CBOE):[A-Z0-9.]+$/.test(want || ''), `${name}: export has tv_symbol for ${row} (${want})`);
  await click(`.row[data-t="${row}"] .cpy`); await page.waitForTimeout(250);
  ok(await clip() === want, `${name}: list card 📋 copied ${want}`);
  ok((await page.textContent('#toast')) === `הועתק: ${want}`, `${name}: toast 'הועתק: ${want}'`);
  ok(!(await page.evaluate(() => location.hash.startsWith('#/t/'))), `${name}: 📋 does not open the stock`);
  if (mobile) await page.screenshot({ path: `${OUT}/10_list_copy_toast.png` });
  // whole filtered list
  await page.fill('#q', 'SN'); await page.waitForTimeout(200);
  const vis = await page.$$eval('.row', (els) => els.map((e) => e.dataset.t));
  await click('#copyList'); await page.waitForTimeout(250);
  ok(await clip() === vis.map((t) => idx[t] || t).join(','), `${name}: list copy = ${vis.length} symbols (${(await clip()).slice(0, 60)})`);
  await page.fill('#q', '');
  // stock page header: SNX (NYSE) and a class share / ETF when present
  for (const t of ['SNX', 'SPY', 'MOG-A'].filter((x) => idx[x])) {
    await page.goto(BASE + '?demo=1#/t/' + t); await page.waitForSelector('#tkCopy'); await page.waitForTimeout(400);
    await click('#tkCopy'); await page.waitForTimeout(250);
    ok(await clip() === idx[t], `${name}: stock page ${t} 📋 -> ${idx[t]}`);
    if (mobile && t === 'SNX') await page.screenshot({ path: `${OUT}/11_snx_copy_toast.png` });
  }
  ok(idx['SNX'] === 'NYSE:SNX', `${name}: SNX is NYSE:SNX on TradingView`);
  await ctx.close();
}
// no Clipboard API -> selected text sheet (or execCommand)
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await ctx.addInitScript(() => { Object.defineProperty(navigator, 'clipboard', { value: undefined }); document.execCommand = () => false; });
  const page = await ctx.newPage(); page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/t/SNX'); await page.waitForSelector('#tkCopy'); await page.waitForTimeout(300);
  await page.locator('#tkCopy').tap(); await page.waitForTimeout(200);
  const sel = await page.evaluate(() => { const ta = document.querySelector('.copybox textarea'); return ta && { v: ta.value, s: ta.selectionStart, e: ta.selectionEnd }; });
  ok(sel && sel.v === 'NYSE:SNX' && sel.s === 0 && sel.e === 8, `fallback: text shown selected (${JSON.stringify(sel)})`);
  await ctx.close();
}
ok(errors.length === 0, `no page errors ${errors.join(' | ')}`);
await browser.close();
