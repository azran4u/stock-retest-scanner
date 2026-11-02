// Expert method primary (Eyal 2026-11-02): the stock page says which levels count ("מומחים" / "שלך") and offers
// "↺ חזרה לרמות המומחים" when his own drawing overrides a valid expert zone; reset -> expert pair active. iPhone + laptop.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4175/stock-retest-scanner/app/';
const OUT = '/workspace/mobile_shots/expert_primary'; mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch(); const errors = [];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage(); page.on('pageerror', (e) => errors.push(e.message)); page.on('dialog', (d) => d.accept());
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.waitForFunction(() => window.__srs.expertDoc != null);
  const t = await page.evaluate(() => {
    const s = window.__srs, ds = [...s.S.drawings.values()];
    return Object.entries(s.expertDoc.tickers).map(([t, z]) => t).find((t) => s.expertDoc.tickers[t].ok && s.expertDoc.tickers[t].trade &&
      ds.some((d) => d.ticker === t && (d.source === 'tv' || d.source === 'user') && d.kind === 'zone' && d.status === 'active'));
  });
  ok(!!t, `${name}: demo ticker with his zone + a valid expert zone: ${t}`);
  await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#srcLine', { timeout: 15000 });
  const s1 = await page.locator('#srcLine').getAttribute('data-zone');
  ok(s1 === 'שלך' && await page.locator('#resetExpert').count() === 1, `${name}: his zone counts ('${s1}') + reset button`);
  await page.locator('#srcLine').scrollIntoViewIfNeeded(); await page.screenshot({ path: `${OUT}/${name}_${t}_his.png` });
  await page.locator('#resetExpert').click(); await page.waitForTimeout(800);
  const z2 = await page.locator('#srcLine').getAttribute('data-zone'), l2 = await page.locator('#srcLine').getAttribute('data-long');
  ok(z2 === 'מומחים' && l2 === 'מומחים', `${name}: after reset zone='${z2}' long='${l2}'`);
  ok(await page.locator('.badge.b-expert').count() >= 2, `${name}: "מומחים" badges on the cards`);
  await page.locator('#srcLine').scrollIntoViewIfNeeded(); await page.screenshot({ path: `${OUT}/${name}_${t}_expert.png` });
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
