// Distance from the expert zone (Eyal 2026-11-01): filter 'מרחק מאזור המומחים ≤ X ATR' (default 1, persisted), sort
// 'קרוב לאזור המומחים', distance on the list badge and in the stock page expert section. Distance in weekly ATRs:
// 0 inside, (price - top)/A above, (bottom - price)/A below (computed here independently from expert_zones.json).
// Demo mode, iPhone 390 + laptop 1366. Usage: node e2e_expert_dist.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/expert_zone_dist';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.evaluate(() => localStorage.removeItem('srs-app-v1')); await page.reload(); await page.waitForSelector('.row');
  await page.waitForFunction(() => window.__srs.expertDoc != null); await page.waitForTimeout(300);
  const st0 = await page.evaluate(() => window.__srs.S.rows.map((r) => [r.ticker, window.__srs.liveOf(r)?.status ?? r.status]));
  // independent expected distances (signed: below < 0)
  const dist = () => page.evaluate(() => { const { S, factsOf, expertDoc } = window.__srs; const o = {};
    for (const r of S.rows) { if (factsOf(r).unfit) continue; const e = expertDoc.tickers[r.ticker]; if (!e?.ok) continue;
      const q = S.quotes.get(r.ticker)?.price, px = q ?? (r.current_price != null ? +r.current_price : e.price), A = e.atr_w;
      o[r.ticker] = px > e.top ? (px - e.top) / A : px < e.bottom ? -(e.bottom - px) / A : 0; } return o; });
  const D = await dist();
  const want = (x) => Object.keys(D).filter((t) => Math.abs(D[t]) <= x + 1e-9).sort();
  const shown = () => page.$$eval('.row', (els) => els.map((e) => e.dataset.t));
  await page.locator('#ftog').click();
  const fi = page.locator('.fi[data-f="expertnear"]');
  ok((await fi.textContent()).includes('מרחק מאזור המומחים') && await fi.locator('.fx').inputValue() === '1', `${name}: filter listed, default 1 ATR`);
  await fi.locator('input[type=checkbox]').click(); await page.waitForTimeout(300);
  let got = (await shown()).sort();
  ok(want(1).length > 0 && JSON.stringify(got) === JSON.stringify(want(1)), `${name}: ≤ 1 ATR -> ${want(1).length} stocks`);
  await fi.locator('.fx').fill('0.5'); await page.waitForTimeout(300);
  got = (await shown()).sort();
  ok(JSON.stringify(got) === JSON.stringify(want(0.5)), `${name}: ≤ 0.5 ATR -> ${want(0.5).length} stocks`);
  // badge distance matches
  const bd = await page.$$eval('.row', (els) => els.map((e) => [e.dataset.t, +e.querySelector('.b-expert')?.dataset.edist]));
  ok(bd.length && bd.every(([t, v]) => Math.abs(v - D[t]) < 1e-3), `${name}: list badge shows the signed distance`);
  await fi.locator('.fx').fill('1'); await page.waitForTimeout(300);
  await page.locator('#sort').selectOption('expertnear'); await page.waitForTimeout(300);
  const ds = (await shown()).map((t) => Math.abs(D[t]));
  ok(ds.length > 1 && ds.every((v, i) => i === 0 || ds[i - 1] <= v + 1e-9), `${name}: sorted closest first (${ds.slice(0, 5).map((v) => v.toFixed(2)).join(', ')}…)`);
  if (!mobile) await page.locator('#ftog').click();
  await page.screenshot({ path: `${OUT}/${name}_list_filter_sort.png` });
  await page.reload(); await page.waitForSelector('.row'); await page.waitForFunction(() => window.__srs.expertDoc != null); await page.waitForTimeout(300);
  const ui = await page.evaluate(() => JSON.parse(localStorage.getItem('srs-app-v1') || '{}'));
  ok(ui.sort === 'expertnear' && ui.f?.expertnear?.on === true && +ui.f.expertnear.x === 1, `${name}: filter + value + sort persisted`);
  ok(JSON.stringify((await shown()).sort()) === JSON.stringify(want(1)), `${name}: same list after reload`);
  const st1 = await page.evaluate(() => window.__srs.S.rows.map((r) => [r.ticker, window.__srs.liveOf(r)?.status ?? r.status]));
  ok(JSON.stringify(st0) === JSON.stringify(st1), `${name}: PASS / statuses unchanged`);
  // stock page: an inside / above / below example where available
  const pick = [Object.keys(D).find((t) => D[t] === 0), Object.keys(D).find((t) => D[t] > 0), Object.keys(D).find((t) => D[t] < 0)].filter(Boolean);
  for (const t of pick) {
    await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#secExpert'); await page.waitForTimeout(400);
    const el = page.locator('#secExpert [data-expdist]');
    const v = +(await el.getAttribute('data-expdist')), tx = await el.textContent();
    const side = D[t] === 0 ? 'בתוך' : D[t] > 0 ? 'מעל' : 'מתחת';
    ok(Math.abs(v - D[t]) < 1e-3 && tx.includes(side) && (D[t] === 0 || tx.includes(Math.abs(D[t]).toFixed(2))), `${name} ${t}: stock page '${tx.trim()}'`);
    await el.scrollIntoViewIfNeeded(); await page.waitForTimeout(150);
    await page.screenshot({ path: `${OUT}/${name}_${t}_${side === 'בתוך' ? 'inside' : side === 'מעל' ? 'above' : 'below'}.png` });
  }
  // v4 higher shelf (STLD): chart draws the active shelf zone, the stock page shows the shelf lows + the origin level
  const sh = await page.evaluate(() => window.__srs.expertDoc.tickers.STLD);
  if (sh?.shelf) {
    await page.goto(BASE + '?demo=1#/t/STLD'); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(500);
    await page.locator('[data-tf="W"]').click(); await page.waitForTimeout(500);
    const g = await page.evaluate(({ e }) => { const cv = window.__srs.cv, r = document.querySelector('#chart g.expert rect'); if (!r) return null;
      return { dTop: Math.abs(+r.getAttribute('y') - cv.candles.priceToCoordinate(e.top)), dBot: Math.abs(+r.getAttribute('y') + +r.getAttribute('height') - cv.candles.priceToCoordinate(e.bottom)) }; }, { e: sh });
    ok(g && g.dTop < 1.5 && g.dBot < 1.5, `${name} STLD: chart zone = shelf ${sh.bottom}-${sh.top}`);
    await page.screenshot({ path: `${OUT}/${name}_STLD_shelf_weekly.png` });
    const tx = await page.locator('#secExpert [data-shelf]').textContent();
    ok(tx.includes('216.36') && tx.includes(sh.origin.top.toFixed(2)) && tx.includes('Weinstein'), `${name} STLD: shelf lows + origin ${sh.origin.bottom}-${sh.origin.top} on the stock page`);
    await page.locator('#secExpert').scrollIntoViewIfNeeded(); await page.waitForTimeout(150);
    await page.screenshot({ path: `${OUT}/${name}_STLD_shelf_panel.png` });
  } else ok(false, `${name}: STLD has no shelf`);
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
