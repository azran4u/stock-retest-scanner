// Per-stock chart view (Eyal 2026-10-31: "switching stocks keeps the previous stock's price axis, the new stock is
// off-screen"). A = GS (~$900), B = SAN (~$11). Open A, zoom the time axis + drag the price axis (manual price scale),
// switch to B (split: list click; phone: next stock via hash) -> B's last close is on screen and roughly centred;
// back to A -> A's view (time range + manual price range) restored; reload -> still restored.
// Usage: node e2e_chart_view.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/chart_view';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const A = 'GS', B = 'SAN';
const browser = await chromium.launch();
const errors = [];
const state = (p) => p.evaluate(() => {
  const cv = window.__srs.cv; const bars = cv.bars; const last = bars[bars.length - 1];
  const ps = cv.chart.priceScale('right'); const lr = cv.chart.timeScale().getVisibleLogicalRange();
  const y = cv.candles.priceToCoordinate(last.close); const H = cv.chart.paneSize().height;
  return { ticker: window.__srs.S.ticker, n: bars.length, close: last.close, auto: ps.options().autoScale !== false, pr: ps.getVisibleRange(),
    lf: lr.from - bars.length, lt: lr.to - bars.length, y, H };
});
const waitT = async (p, t) => { await p.waitForFunction((t) => window.__srs?.S.ticker === t && window.__srs.cv?.bars.length > 0 && window.__srs.cv.bars[window.__srs.cv.bars.length - 1] && document.querySelector('#tk')?.textContent?.includes(t), t, { timeout: 15000 }); await p.waitForTimeout(700); };
const near = (a, b, tol) => Math.abs(a - b) <= tol;
for (const [name, vp, mobile] of [['laptop_1366', { width: 1366, height: 768 }, false], ['ipad_landscape_1180', { width: 1180, height: 820 }, true], ['iphone_390', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  await ctx.addInitScript(() => { if (!sessionStorage.getItem('init')) { localStorage.clear(); sessionStorage.setItem('init', '1'); } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + `?demo=1#/t/${A}`); await waitT(page, A);
  const box = await page.locator('#chart').boundingBox();
  const s0 = await state(page);
  ok(s0.auto && s0.y > 0 && s0.y < s0.H, `${name}: ${A} opens auto-fit with the last close on screen`);
  // time zoom (wheel / programmatic on touch) + price-axis drag = manual price scale
  if (!mobile) { await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.4); await page.mouse.wheel(0, -400); }
  else await page.evaluate(() => { const ts = window.__srs.cv.chart.timeScale(); const r = ts.getVisibleLogicalRange(); ts.setVisibleLogicalRange({ from: r.from + 40, to: r.to - 2 }); });
  await page.waitForTimeout(300);
  const ax = box.x + box.width - 25, ay = box.y + box.height * 0.35;
  await page.mouse.move(ax, ay); await page.mouse.down(); await page.mouse.move(ax, ay + 90, { steps: 8 }); await page.mouse.up();
  await page.waitForTimeout(500);
  const sA = await state(page);
  ok(!sA.auto, `${name}: price axis dragged -> manual price scale ${sA.pr.from.toFixed(1)}-${sA.pr.to.toFixed(1)}`);
  ok(Math.abs(sA.lf - s0.lf) > 3, `${name}: time range changed (${s0.lf.toFixed(0)} -> ${sA.lf.toFixed(0)})`);
  await page.screenshot({ path: `${OUT}/${name}_1_${A}_zoomed.png` });
  // -> B
  if (!mobile && await page.$('.split')) {
    await page.locator('#q').fill(B); await page.waitForTimeout(300);
    await page.locator(`.side .row[data-t="${B}"]`).click();
  } else await page.evaluate((t) => { location.hash = '#/t/' + t; }, B);
  await waitT(page, B);
  const sB = await state(page);
  ok(sB.y > 0 && sB.y < sB.H, `${name}: ${B} (${sB.close}) last close on screen (y ${Math.round(sB.y)} of ${Math.round(sB.H)})`);
  ok(Math.abs(sB.y - sB.H / 2) < sB.H * 0.25, `${name}: ${B} last close roughly centred (y ${Math.round(sB.y)}, mid ${Math.round(sB.H / 2)})`);
  ok(sB.auto, `${name}: ${B} has auto price scale (no leftover manual range from ${A})`);
  await page.screenshot({ path: `${OUT}/${name}_2_${B}_centred.png` });
  // back to A
  if (await page.$('.split') && !mobile) { await page.locator('#q').fill(A); await page.waitForTimeout(300); await page.locator(`.side .row[data-t="${A}"]`).click(); }
  else await page.evaluate((t) => { location.hash = '#/t/' + t; }, A);
  await waitT(page, A);
  const sA2 = await state(page);
  ok(!sA2.auto && near(sA2.pr.from, sA.pr.from, 0.5) && near(sA2.pr.to, sA.pr.to, 0.5), `${name}: ${A} manual price range restored (${sA2.pr.from.toFixed(1)}-${sA2.pr.to.toFixed(1)})`);
  ok(near(sA2.lf, sA.lf, 1) && near(sA2.lt, sA.lt, 1), `${name}: ${A} time range restored`);
  await page.screenshot({ path: `${OUT}/${name}_3_${A}_restored.png` });
  await page.reload(); await waitT(page, A);
  const sA3 = await state(page);
  ok(!sA3.auto && near(sA3.pr.from, sA.pr.from, 0.5) && near(sA3.pr.to, sA.pr.to, 0.5) && near(sA3.lf, sA.lf, 1), `${name}: ${A} view still restored after reload`);
  await ctx.close();
}
ok(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);
await browser.close();
