// Expert zones for ALL stocks (Eyal 2026-11-01 20:47/20:48): list badge on every stock that has one, filter 'יש אזור
// מומחים, ציון ≥' (default 0, persisted), sort 'ציון מומחים (גבוה תחילה)' (persisted), expert trade (Entry / SL / TP) box
// on the weekly + daily chart (toggle = the expert chip) and its numbers on the stock page. Never changes PASS / drawings.
// Demo mode, iPhone 390 + laptop 1366. Usage: node e2e_expert_all.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/expert_zone_all';
mkdirSync(OUT, { recursive: true });
const doc = JSON.parse(readFileSync(new URL('../app/data/expert_zones.json', import.meta.url)));
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
  // expected set (independent of filters.ts): visible rows (unfit hidden by default) with an expert zone
  const want = (min) => page.evaluate(({ min }) => { const { S, factsOf, expertDoc } = window.__srs;
    return S.rows.filter((r) => !factsOf(r).unfit).filter((r) => { const e = expertDoc.tickers[r.ticker]; return e?.ok && e.score >= min; }).map((r) => r.ticker).sort(); }, { min });
  const shown = () => page.$$eval('.row', (els) => els.map((e) => e.dataset.t));
  const nOk = Object.values(doc.tickers).filter((e) => e.ok).length;
  // badges
  const badgeCount = await page.locator('.row .b-expert').count();
  ok(badgeCount > 0, `${name}: list badges shown (${badgeCount} rendered rows with one; ${nOk} tickers have an expert zone)`);
  // filter
  await page.locator('#ftog').click();
  const fi = page.locator('.fi[data-f="expert"]');
  ok((await fi.textContent()).includes('יש אזור מומחים') && await fi.locator('.fx').inputValue() === '0', `${name}: filter listed, default min 0`);
  await fi.locator('input[type=checkbox]').click(); await page.waitForTimeout(300);
  let w = await want(0), got = (await shown()).sort();
  ok(w.length > 0 && JSON.stringify(got) === JSON.stringify(w), `${name}: filter -> ${w.length} stocks with an expert zone`);
  ok(await page.locator('.row').count() === await page.locator('.row .b-expert').count(), `${name}: every filtered row has the badge`);
  await fi.locator('.fx').fill('50'); await page.waitForTimeout(300);
  w = await want(50); got = (await shown()).sort();
  ok(JSON.stringify(got) === JSON.stringify(w), `${name}: min score 50 -> ${w.length}`);
  await fi.locator('.fx').fill('0'); await page.waitForTimeout(300);
  // sort
  await page.locator('#sort').selectOption('expert'); await page.waitForTimeout(300);
  const sc = await page.$$eval('.row', (els) => els.map((e) => window.__srs.expertDoc.tickers[e.dataset.t]?.score ?? -1));
  ok(sc.length > 1 && sc.every((v, i) => i === 0 || sc[i - 1] >= v), `${name}: sorted by expert score, highest first (${sc.slice(0, 5).join(', ')}…)`);
  if (!mobile) await page.locator('#ftog').click();
  await page.screenshot({ path: `${OUT}/${name}_list_filter_sort.png` });
  // persisted
  await page.reload(); await page.waitForSelector('.row'); await page.waitForFunction(() => window.__srs.expertDoc != null); await page.waitForTimeout(300);
  const ui = await page.evaluate(() => JSON.parse(localStorage.getItem('srs-app-v1') || '{}'));
  ok(ui.sort === 'expert' && ui.f?.expert?.on === true, `${name}: filter + sort persisted`);
  const st1 = await page.evaluate(() => window.__srs.S.rows.map((r) => [r.ticker, window.__srs.liveOf(r)?.status ?? r.status]));
  ok(JSON.stringify(st0) === JSON.stringify(st1), `${name}: PASS / statuses unchanged`);
  // top stock: trade box + numbers
  const top = (await shown())[0], e = doc.tickers[top];
  const drawBefore = await page.evaluate(() => JSON.stringify(window.__demoApi.drawings));
  await page.goto(BASE + `?demo=1#/t/${top}`); await page.waitForSelector('#chart canvas');
  await page.waitForFunction(() => window.__srs.expertDoc != null); await page.waitForTimeout(500);
  for (const tf of ['W', 'D']) {
    await page.locator(`[data-tf="${tf}"]`).click(); await page.waitForTimeout(500);
    const g = await page.evaluate(({ tr }) => {
      const cv = window.__srs.cv, el = document.querySelector('#chart g.experttrade'); if (!el) return null;
      const line = el.querySelector('line'), y = cv.candles.priceToCoordinate(tr.entry);
      const last = cv.chart.timeScale().logicalToCoordinate(cv.bars.length - 1), x1 = +el.querySelector('rect').getAttribute('x');
      return { dy: Math.abs(+line.getAttribute('y1') - y), right: x1 > last, label: el.querySelector('text').textContent };
    }, { tr: e.trade });
    ok(g && g.dy < 1.5 && g.right && g.label === `מומחים R:R ${e.trade.rr.toFixed(2)}`, `${name} ${top} ${tf}: expert trade box at E ${e.trade.entry} right of the last candle, '${g?.label}'`);
    await page.screenshot({ path: `${OUT}/${name}_${top}_${tf === 'W' ? 'weekly' : 'daily'}.png` });
  }
  await page.locator('[data-expert]').click(); await page.waitForTimeout(250);
  ok(await page.locator('#chart g.experttrade').count() === 0 && await page.locator('#chart g.expert').count() === 0, `${name}: chip hides zone + trade`);
  await page.locator('[data-expert]').click(); await page.waitForTimeout(250);
  const tx = await page.locator('#secExpert .exptrade').textContent();
  ok(tx.includes(e.trade.entry.toFixed(2)) && tx.includes(e.trade.sl.toFixed(2)) && tx.includes(e.trade.tp.toFixed(2)) && tx.includes('Bulkowski'), `${name} ${top}: Entry / SL / TP + sources on the stock page`);
  await page.locator('#secExpert').scrollIntoViewIfNeeded(); await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT}/${name}_${top}_trade_panel.png` });
  ok(await page.evaluate(() => JSON.stringify(window.__demoApi.drawings)) === drawBefore, `${name}: drawings untouched`);
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
