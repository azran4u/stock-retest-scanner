// Institutional ownership % + short float % next to every ticker (Eyal 2026-10-31): one line 'מוסדיים 72% · SF 3.1%'
// under the ticker on every list card (single list, split-view side list, phone) and in the stock page header; funds /
// unknown -> '—' (never filtered out); the ticker 📋 copy button keeps working. Laptop split, iPad, iPhone.
// Usage: node e2e_ownership.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/ownership';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const fmtI = (v) => (v == null ? '—' : `${v >= 10 ? Math.round(v) : v.toFixed(1)}%`);
const fmtS = (v) => (v == null ? '—' : `${v.toFixed(1)}%`);
const want = (r) => `מוסדיים ${fmtI(r.inst_own_pct)} · SF ${fmtS(r.short_float_pct)}`;
const browser = await chromium.launch();
const errors = [];
const origin = new URL(BASE).origin;
for (const [name, vp, mobile, split] of [['laptop_1366', { width: 1366, height: 768 }, false, true],
  ['ipad_820', { width: 820, height: 1180 }, true, true], ['iphone_390', { width: 390, height: 844 }, true, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1'); await page.waitForSelector('.row .own'); await page.waitForTimeout(300);
  const rows = await page.evaluate(() => window.__srs.S.rows.map((r) => ({ ticker: r.ticker, status: r.status, inst_own_pct: r.inst_own_pct ?? null, short_float_pct: r.short_float_pct ?? null })));
  const nI = rows.filter((r) => r.inst_own_pct != null).length, nS = rows.filter((r) => r.short_float_pct != null).length;
  if (name === 'laptop_1366') console.log(`     data: ${rows.length} rows, inst ${nI}, short ${nS}`);
  ok(nI > rows.length * 0.5 && nS > rows.length * 0.5, `${name}: most rows have inst own / short float (${nI} / ${nS} of ${rows.length})`);
  // every rendered card shows the line, matching its row
  const cards = await page.$$eval('.row', (els) => els.slice(0, 40).map((e) => ({ t: e.dataset.t, own: e.querySelector('.own')?.textContent?.trim() || null })));
  const byT = Object.fromEntries(rows.map((r) => [r.ticker, r]));
  ok(cards.length > 0 && cards.every((c) => c.own === want(byT[c.t])), `${name}: ${cards.length} cards show 'מוסדיים x% · SF y%' matching the data (${cards[0]?.t}: ${cards[0]?.own})`);
  ok(!!(await page.$('.split')) === split, `${name}: ${split ? 'split view (side list)' : 'single list'}`);
  // a fund (no FinViz values) still listed, with '—'
  const fund = rows.find((r) => r.inst_own_pct == null && r.short_float_pct == null);
  if (fund) {
    await page.fill('#q', fund.ticker); await page.waitForTimeout(300);
    ok((await page.locator(`.row[data-t="${fund.ticker}"] .own`).textContent()).trim() === 'מוסדיים — · SF —', `${name}: ${fund.ticker} without data is listed with '—'`);
  }
  const st = rows.find((r) => r.inst_own_pct != null && r.short_float_pct != null && r.ticker === 'CSCO') || rows.find((r) => r.inst_own_pct != null);
  await page.fill('#q', st.ticker); await page.waitForTimeout(300);
  // copy button next to the ticker still copies (and does not open the stock)
  const cp = page.locator(`.row[data-t="${st.ticker}"] .cpy`);
  const sym = await cp.getAttribute('data-copy');
  if (mobile) await cp.tap(); else await cp.click();
  await page.waitForTimeout(250);
  ok(await page.evaluate(() => navigator.clipboard.readText()) === sym, `${name}: list 📋 still copies ${sym}`);
  // the line sits right under the ticker line, inside the card, not overflowing it
  const geo = await page.evaluate((t) => { const c = document.querySelector(`.row[data-t="${t}"]`); const o = c.querySelector('.own'); const r1 = c.querySelector('.r1');
    const a = c.getBoundingClientRect(), b = o.getBoundingClientRect(), h = r1.getBoundingClientRect(); return { in: b.left >= a.left - 1 && b.right <= a.right + 1, under: b.top >= h.bottom - 4 && b.top - h.bottom < 12, clip: o.scrollWidth > o.clientWidth + 1 }; }, st.ticker);
  ok(geo.in && geo.under && !geo.clip, `${name}: line right under the ticker, fits the card (${JSON.stringify(geo)})`);
  await page.screenshot({ path: `${OUT}/${name}_list_e2e.png` });
  // stock page header
  if (split && mobile) await page.locator(`.row[data-t="${st.ticker}"] .r1 b`).tap();
  else if (split) await page.locator(`.row[data-t="${st.ticker}"] .r1 b`).click();
  else await page.evaluate((t) => { location.hash = '#/t/' + t; }, st.ticker);
  await page.waitForFunction((t) => document.querySelector('#tk')?.textContent === t, st.ticker);
  await page.waitForTimeout(500);
  const hd = (await page.locator('#tkown').textContent()).trim();
  ok(hd === want(st), `${name}: stock header ${st.ticker} shows '${hd}'`);
  ok(await page.locator('#tkown').isVisible(), `${name}: header value visible`);
  const hb = await page.locator('#tkown').boundingBox();
  ok(hb.x >= 0 && hb.x + hb.width <= vp.width + 1, `${name}: header value inside the screen`);
  ok((await page.locator('#tkown').getAttribute('title')).startsWith('FinViz'), `${name}: tooltip names the source/date`);
  if (mobile) await page.locator('#tkCopy').tap(); else await page.locator('#tkCopy').click();
  await page.waitForTimeout(250);
  ok(await page.evaluate(() => navigator.clipboard.readText()) === sym, `${name}: header 📋 still copies ${sym}`);
  await page.screenshot({ path: `${OUT}/${name}_stock_e2e.png` });
  await ctx.close();
}
ok(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);
await browser.close();
