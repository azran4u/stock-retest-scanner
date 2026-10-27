// Eyal 2026-10-27 "AVDE and SCZ show the same chart": each list card draws its own ticker's mini chart (different
// pixels, its own min/max labels), and a row flagged by the export duplicate-series guard (data_dup_of) shows a warning
// on the card and the stock page. iPhone 390. Usage: node e2e_dup_series.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/avde_scz';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const page = await ctx.newPage(); const errors = []; page.on('pageerror', (e) => errors.push(e.message));
await page.goto(BASE + '?demo=1'); await page.waitForSelector('.row');
const px = {};
for (const t of ['AVDE', 'SCZ']) {
  await page.fill('#q', t); await page.waitForSelector(`.row[data-t="${t}"] canvas.spark[data-drawn]`, { timeout: 10000 });
  px[t] = await page.evaluate((t) => { const c = document.querySelector(`.row[data-t="${t}"] canvas.spark`); return { key: c.dataset.spark, url: c.toDataURL() }; }, t);
  ok(px[t].key === t, `${t}: card canvas keyed by its own ticker`);
}
ok(px.AVDE.url !== px.SCZ.url, 'AVDE and SCZ mini charts differ (pixels)');
const sp = await page.evaluate(async () => (await (await fetch('data/spark.json')).json()));
ok(sp.AVDE && sp.SCZ && sp.AVDE.q !== sp.SCZ.q && sp.AVDE.hi !== sp.SCZ.hi, `spark data differ (hi ${sp.AVDE?.hi} vs ${sp.SCZ?.hi})`);
// flagged row -> warning on the card and the stock page
await page.evaluate(() => { const S = window.__srs.S; S.byT.get('SCZ').data_dup_of = 'AVDE'; });
await page.fill('#q', 'SCZ'); await page.waitForTimeout(300);
ok(/זהים ל-AVDE/.test(await page.textContent('.row[data-t="SCZ"]')), 'flagged card shows the duplicate warning');
await page.goto(BASE + '?demo=1#/t/SCZ'); await page.waitForSelector('#panel section');
await page.evaluate(() => { window.__srs.S.byT.get('SCZ').data_dup_of = 'AVDE'; window.__srs.refreshLive(); });
await page.waitForTimeout(300);
ok(await page.locator('#panel .dupwarn').count() === 1, 'flagged stock page shows the duplicate warning');
await page.fill('#cmd', '').catch(() => {});
ok(errors.length === 0, `no page errors ${errors.join(' | ')}`);
await browser.close();
