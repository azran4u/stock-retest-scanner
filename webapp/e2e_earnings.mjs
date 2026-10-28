// Earnings report markers (Eyal 2026-10-28: "add markers on the chart with the past report dates"). Desktop 1440 and
// iPhone 390, demo mode: a stock with earnings (KNX) shows an 'E' badge per past report in the weekly and daily views
// plus a hollow badge for the next date in the future area; hover (desktop) / tap (mobile) shows the date and EPS vs
// estimate; an ETF (first fund in earnings-less tickers, e.g. URA) shows none; the "דוחות" chip hides / shows them and
// is remembered (localStorage, on by default). Usage: node e2e_earnings.mjs [baseURL] [outDir] [ticker]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/earnings_markers';
const TK = process.argv[4] || 'KNX';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const earn = await (await fetch(BASE + 'data/earnings.json')).json();
const idx = await (await fetch(BASE + 'data/index.json')).json();
const cand = idx.rows.filter((r) => r.has_candles);
const etf = ['URA', 'SPY', 'QQQ', 'IWM', 'XAR', 'ITA', 'PSI', 'SOXL'].find((t) => cand.some((r) => r.ticker === t) && !earn[t]);
ok(earn[TK] && earn[TK].p.length >= 8, `export: ${TK} has ${earn[TK]?.p.length} past report dates`);
ok(!!etf, `export: ETF ${etf} has no earnings entry`);
const since5y = new Date(Date.now() - 5 * 365.25 * 864e5).toISOString().slice(0, 10);
const nPast = earn[TK].p.filter((p) => p.d >= since5y).length;

for (const [name, vp, mobile] of [['desktop', { width: 1440, height: 900 }, false], ['mobile', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`));
  const click = (loc) => (mobile ? loc.tap() : loc.click());
  await page.goto(BASE + `?demo=1#/t/${TK}`);
  await page.waitForSelector('#chart canvas'); await page.waitForTimeout(1500);
  ok(await page.locator('[data-earn]').isVisible() && await page.locator('[data-earn].on').count() === 1, `${name}: "דוחות" chip visible and on by default`);
  // weekly: zoom out so the whole history is on screen, then count the badges
  const fitAll = () => page.evaluate(() => { const ts = window.__srs?.cv?.chart?.timeScale?.(); ts?.fitContent(); });
  await page.waitForSelector('#chart g.earn');
  await fitAll(); await page.waitForTimeout(400);
  const past = await page.locator('#chart g.earn:not(.next)').count();
  const next = await page.locator('#chart g.earn.next').count();
  ok(past >= Math.min(nPast, 8), `${name} weekly: ${past} past 'E' markers (export: ${nPast} in 5y)`);
  ok(next === (earn[TK].n ? 1 : 0), `${name} weekly: next-report marker in the future area (${earn[TK].n})`);
  if (next) {
    const nx = await page.evaluate(() => { const c = document.querySelector('#chart g.earn.next circle:nth-of-type(2)'); return c ? +c.getAttribute('cx') : null; });
    const lastPast = await page.evaluate(() => Math.max(...[...document.querySelectorAll('#chart g.earn:not(.next) circle:nth-of-type(2)')].map((c) => +c.getAttribute('cx'))));
    ok(nx > lastPast, `${name} weekly: next marker right of the last past one`);
  }
  // reset the default zoom (last ~110 weeks) for the screenshot + tooltip
  await page.locator('[data-tf="D"]').first().click(); await page.waitForTimeout(300);
  await page.locator('[data-tf="W"]').first().click(); await page.waitForTimeout(800);
  const last = earn[TK].p[earn[TK].p.length - 1];
  const g = page.locator(`#chart g.earn[data-d="${last.d}"]`);
  ok(await g.count() === 1, `${name}: marker for the last report ${last.d}`);
  if (mobile) await g.tap(); else await g.hover();
  await page.waitForTimeout(300);
  const tip = await page.locator('#chart .etip').textContent();
  const dd = `${last.d.slice(8, 10)}.${last.d.slice(5, 7)}.${last.d.slice(0, 4)}`;
  ok(await page.locator('#chart .etip').isVisible() && tip.includes(dd), `${name}: ${mobile ? 'tap' : 'hover'} shows the date (${tip})`);
  if (last.a != null && last.e != null) ok(tip.includes(last.a.toFixed(2)) && tip.includes(last.e.toFixed(2)), `${name}: tooltip has EPS ${last.a} vs estimate ${last.e}`);
  await page.screenshot({ path: `${OUT}/${TK}_${name}_weekly.png` });
  if (mobile) { await g.tap(); await page.waitForTimeout(200); ok(await page.locator('#chart .etip').isHidden(), `${name}: second tap closes the tooltip`); }
  else { await page.mouse.move(5, 5); await page.waitForTimeout(200); ok(await page.locator('#chart .etip').isHidden(), `${name}: tooltip hides on mouse out`); }
  // daily
  await click(page.locator('[data-tf="D"]').first()); await page.waitForTimeout(800);
  await fitAll(); await page.waitForTimeout(400);
  const pd = await page.locator('#chart g.earn:not(.next)').count();
  ok(pd >= Math.min(nPast, 8), `${name} daily: ${pd} past 'E' markers`);
  // the daily marker sits on the candle of the report date (x of the marker == x of that bar)
  const onBar = await page.evaluate((d) => {
    const cv = window.__srs?.cv; const el = document.querySelector(`#chart g.earn[data-d="${d}"] circle:nth-of-type(2)`);
    if (!cv || !el) return null;
    const i = cv.bars.findIndex((b) => b.time === d); if (i < 0) return 'nobar';
    return Math.abs(cv.chart.timeScale().logicalToCoordinate(i) - +el.getAttribute('cx')) < 1;
  }, last.d);
  ok(onBar === true || onBar === 'nobar', `${name} daily: marker on the report-date candle (${onBar})`);
  await page.locator('[data-tf="W"]').first().click(); await page.waitForTimeout(500);
  if (mobile) await page.screenshot({ path: `${OUT}/${TK}_${name}_daily_fit.png` });
  // toggle off -> no markers; persisted after reload; back on
  await click(page.locator('[data-earn]').first()); await page.waitForTimeout(300);
  ok(await page.locator('#chart g.earn').count() === 0, `${name}: "דוחות" off hides the markers`);
  await page.reload(); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(1500);
  ok(await page.locator('[data-earn].on').count() === 0 && await page.locator('#chart g.earn').count() === 0, `${name}: off is remembered after reload`);
  await click(page.locator('[data-earn]').first()); await page.waitForTimeout(500);
  ok(await page.locator('#chart g.earn').count() > 0, `${name}: back on`);
  // ETF: none
  await page.goto(BASE + `?demo=1#/t/${etf}`); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(1500);
  await fitAll(); await page.waitForTimeout(300);
  ok(await page.locator('#chart g.earn').count() === 0, `${name}: ETF ${etf} has no earnings markers`);
  ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow`);
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.join(' | '));
await browser.close();
