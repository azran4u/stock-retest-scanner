// Open positions bar (Eyal 2026-10-24): values vs formula, price-source fallback + labels, sticky on scroll (list +
// stock page), tap -> stock page, collapse persisted, real CNBC quote from the browser (CORS). Demo mode with MADE-UP
// positions injected (nothing real in the repo). Usage: node e2e_positions.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/positions_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const POS = [
  { id: 'QCOM:2026-09-01', ticker: 'QCOM', exchange: 'NASDAQ', side: 'long', status: 'open', entry_date: '2026-09-01', qty: 3, entry_price: 160, stop: 150, target: 190, market: { date: '2026-10-23', close: 175.91 } },
  { id: 'AAPL:2026-10-01', ticker: 'AAPL', exchange: 'NASDAQ', side: 'long', status: 'open', entry_date: '2026-10-01', qty: 2, entry_price: 250, stop: 240, target: 280, market: { date: '2026-10-23', close: 245 } },
  { id: 'OLD:2026-01-01', ticker: 'OLD', exchange: 'NYSE', side: 'long', status: 'closed', entry_date: '2026-01-01', qty: 1, entry_price: 10, stop: 9, target: 12 },
];
// CNBC mock: QCOM 170.50 at 15:59:59 EDT (= 22:59 Israel), AAPL 236.00
const CNBC = { FormattedQuoteResult: { FormattedQuote: [
  { symbol: 'QCOM', code: 0, last: '170.50', last_time: '2026-10-23T15:59:59.000-0400', last_timedate: '3:59 PM EDT', curmktstatus: 'REG_MKT' },
  { symbol: 'AAPL', code: 0, last: '236.00', last_time: '2026-10-23T15:59:59.000-0400', last_timedate: '3:59 PM EDT', curmktstatus: 'REG_MKT' }] } };
const calc = (p, px) => ({ pl: (px - p.entry_price) * p.qty, plPct: (px / p.entry_price - 1) * 100, r: (px - p.entry_price) / (p.entry_price - p.stop), sl: (p.stop - px) / px * 100, tp: (p.target - px) / px * 100 });
const browser = await chromium.launch();
const errors = [];
const bar = (page) => page.evaluate(() => {
  const b = document.querySelector('#posbar'); if (!b || b.hidden) return null;
  const rows = [...b.querySelectorAll('.pb-row')].map((r) => ({ t: r.dataset.t, px: r.querySelector('.pb-px').dataset.v, pl: r.querySelector('.pb-pl').dataset.v, r: r.querySelector('.pb-r').dataset.v, sl: r.querySelector('.pb-sl').dataset.v, tp: r.querySelector('.pb-tp').dataset.v, plCls: r.querySelector('.pb-pl').className, txt: r.textContent.replace(/\s+/g, ' ').trim() }));
  const rc = b.getBoundingClientRect();
  return { rows, tot: b.querySelector('.pb-tot').dataset.pl, totTxt: b.querySelector('.pb-tot').textContent, totCls: b.querySelector('.pb-tot').className, src: b.querySelector('.pb-src').textContent, top: rc.top, bottom: rc.bottom, rowsHidden: b.querySelector('.pb-rows').hidden };
});
for (const [name, vp, mobile] of [['desktop_1440', { width: 1440, height: 900 }, false], ['iphone_390', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  await ctx.addInitScript((p) => { window.__demoPositions = p; }, POS);
  let mode = 'cnbc';
  await ctx.route(/quote\.cnbc\.com/, (r) => (mode === 'cnbc' ? r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify(CNBC) }) : r.abort()));
  await ctx.route(/scanner\.tradingview\.com/, (r) => (mode === 'tv' ? r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ data: [{ s: 'NASDAQ:QCOM', d: [171.25] }, { s: 'NASDAQ:AAPL', d: [237] }] }) }) : r.abort()));
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && !/net::ERR_FAILED|Failed to load resource/.test(m.text()) && errors.push(m.text()));
  await page.goto(BASE + '?demo=1#/');
  await page.waitForSelector('.row'); await page.waitForSelector('#posbar .pb-row'); await page.waitForTimeout(400);
  let b = await bar(page);
  ok(b && b.rows.length === 2 && !b.rows.some((r) => r.t === 'OLD'), `${name}: bar shows the 2 open positions (closed one hidden)`);
  const px = { QCOM: 170.5, AAPL: 236 };
  for (const r of b.rows) {
    const p = POS.find((x) => x.ticker === r.t), e = calc(p, px[r.t]);
    ok(+r.px === px[r.t] && Math.abs(+r.pl - e.pl) < 1e-9 && Math.abs(+r.r - e.r) < 1e-9 && Math.abs(+r.sl - e.sl) < 1e-9 && Math.abs(+r.tp - e.tp) < 1e-9,
      `${name}: ${r.t} = formula: ${r.txt}`);
    ok(r.plCls.includes(e.pl >= 0 ? 'up' : 'dn'), `${name}: ${r.t} colored ${e.pl >= 0 ? 'green' : 'red'}`);
  }
  const totE = calc(POS[0], 170.5).pl + calc(POS[1], 236).pl;
  const totPct = totE / (160 * 3 + 250 * 2) * 100, totR = totE / (10 * 3 + 10 * 2);
  ok(Math.abs(+b.tot - totE) < 1e-9 && b.totTxt.includes(totPct.toFixed(2).replace('-', '')) && b.totTxt.includes(Math.abs(totR).toFixed(2) + 'R') && b.totCls.includes(totE >= 0 ? 'up' : 'dn'), `${name}: total ${b.totTxt}`);
  ok(/CNBC 23\/10 22:59 \(שעון ישראל\)/.test(b.src), `${name}: price time in Israel time: "${b.src}"`);
  ok(b.top === 0, `${name}: bar at the top`);
  await page.screenshot({ path: `${OUT}/60_posbar_list_${name}.png` }); console.log('     shot', `${OUT}/60_posbar_list_${name}.png`);
  // sticky on scroll: bar stays at 0, list header right under it, nothing hidden behind
  await page.mouse.wheel(0, 2500); await page.evaluate(() => window.scrollTo(0, 2500)); await page.waitForTimeout(300);
  b = await bar(page);
  const hdr = await page.evaluate(() => { const h = document.querySelector('header.top').getBoundingClientRect(); const f = document.querySelector('.filters').getBoundingClientRect(); return { h: h.top, hb: h.bottom, f: f.top, y: scrollY }; });
  ok(hdr.y > 500 && b.top === 0 && Math.abs(hdr.h - b.bottom) <= 1 && Math.abs(hdr.f - hdr.hb) <= 2, `${name}: after scrolling ${hdr.y}px the bar stays on top (0-${b.bottom.toFixed(0)}), header at ${hdr.h.toFixed(0)}, filters at ${hdr.f.toFixed(0)}`);
  await page.screenshot({ path: `${OUT}/61_posbar_scrolled_${name}.png` }); console.log('     shot', `${OUT}/61_posbar_scrolled_${name}.png`);
  // tap a ticker -> its stock page; bar still there, chart header below it, page fits the viewport
  await page.click('#posbar .pb-row[data-t="QCOM"]');
  await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
  b = await bar(page);
  const ch = await page.evaluate(() => ({ hash: location.hash, top: document.querySelector('#chhead').getBoundingClientRect().top, cvb: document.querySelector('.cv').getBoundingClientRect().bottom, vh: innerHeight }));
  ok(ch.hash === '#/t/QCOM' && b && Math.abs(ch.top - b.bottom) <= 1 && ch.cvb <= ch.vh + 1, `${name}: tap QCOM -> stock page, bar on top, chart header at ${ch.top.toFixed(0)}, page bottom ${ch.cvb.toFixed(0)} <= ${ch.vh}`);
  await page.screenshot({ path: `${OUT}/62_posbar_stock_${name}.png` }); console.log('     shot', `${OUT}/62_posbar_stock_${name}.png`);
  // fallback 1: CNBC down -> TradingView (delayed, labelled)
  mode = 'tv'; await page.click('#pbRef'); await page.waitForTimeout(600);
  b = await bar(page);
  ok(+b.rows.find((r) => r.t === 'QCOM').px === 171.25 && /TradingView · מושהה/.test(b.src) && b.rows[0].txt.includes('מושהה'), `${name}: CNBC down -> TradingView: "${b.src}"`);
  // fallback 2: both down -> stored last close, labelled
  mode = 'none'; await page.click('#pbRef'); await page.waitForTimeout(600);
  b = await bar(page);
  ok(+b.rows.find((r) => r.t === 'QCOM').px === 175.91 && /סגירה אחרונה 23\/10/.test(b.src), `${name}: both down -> last close: "${b.src}"`);
  // collapse: persisted across reload
  await page.click('#pbTog'); await page.waitForTimeout(200);
  ok((await bar(page)).rowsHidden, `${name}: collapsed`);
  mode = 'cnbc'; await page.reload(); await page.waitForSelector('#posbar .pb-tot'); await page.waitForTimeout(500);
  b = await bar(page);
  ok(b.rowsHidden && Math.abs(+b.tot - totE) < 1e-9, `${name}: collapse kept after reload, total still shown ${b.totTxt}`);
  await page.click('#pbTog'); await page.waitForTimeout(200);
  ok(!(await bar(page)).rowsHidden, `${name}: expanded again`);
  await ctx.close();
}
// logged out: no bar
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.addInitScript((p) => { window.__demoPositions = p; }, POS);
  const page = await ctx.newPage(); await page.goto(BASE + '?demo=login#/'); await page.waitForTimeout(800);
  ok(await page.locator('#posbar').isHidden(), 'logged out -> no positions bar');
  await ctx.close();
}
// real CNBC from the browser (CORS) - live network, no mock
{
  const ctx = await browser.newContext();
  await ctx.addInitScript((p) => { window.__demoPositions = p; }, POS);
  const page = await ctx.newPage(); await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('#posbar .pb-row'); await page.waitForTimeout(2500);
  const q = await page.evaluate(() => [...window.__srs.S.quotes.entries()].map(([t, q]) => `${t} ${q.src} ${q.price} ${q.at || q.date}`));
  const src = await page.locator('#posbar .pb-src').textContent();
  ok(q.length === 2 && q.every((s) => / cnbc /.test(s)), `real CNBC quotes in the browser: ${q.join(' | ')} -> "${src}"`);
  await ctx.close();
}
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
