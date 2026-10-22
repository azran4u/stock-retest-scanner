// Chart features smoke test (demo mode, iPhone 390x844, touch): weekly ATR corner label, dashed drag guide,
// SL size label, Long Position time anchor (pan / zoom). Usage: node e2e_chart.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'he-IL' });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const cdp = await ctx.newCDPSession(page);
const touch = (type, x, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y, id: 1 }] });
const shot = async (n) => { await page.screenshot({ path: `${OUT}/${n}.png` }); console.log('     shot', `${OUT}/${n}.png`); };

await page.goto(BASE + '?demo=1#/t/CSCO');
await page.waitForSelector('#chart canvas'); await page.waitForTimeout(800);
page.on('dialog', (d) => d.accept());

// ---- 1. weekly ATR bottom-right ----
const chart = await page.locator('#chart').boundingBox();
const atrBox = await page.locator('.atrw').boundingBox();
const atrTxt = await page.locator('.atrw').innerText();
const exp = await page.evaluate(() => { const s = window.__srs; return { calc: s.atr(s.cv.bars).toFixed(2), scan: s.S.byT.get('CSCO')?.weekly_atr }; });
ok(/ATR\(W\)\s*[\d.]+/.test(atrTxt) && atrTxt.includes(exp.calc), `ATR label "${atrTxt.replace(/\s+/g, ' ')}" = Wilder14(weekly) ${exp.calc} (scanner wATR ${exp.scan})`);
ok(Math.abs(atrBox.x + atrBox.width - (chart.x + chart.width)) < 2 && Math.abs(atrBox.y + atrBox.height - (chart.y + chart.height)) < 2, `ATR box in bottom-right corner ${JSON.stringify(atrBox)}`);
await shot('01_atr_weekly');
await page.tap('[data-tf="D"]'); await page.waitForTimeout(400);
ok((await page.locator('.atrw').innerText()).includes(exp.calc), 'daily view still shows the weekly ATR');
await shot('02_atr_daily');
await page.tap('[data-tf="W"]'); await page.waitForTimeout(400);

// ---- 2. create a long (2 taps), anchored in time ----
// hide the demo TV rows (soft delete in the in-memory backend) so only the new long is on the chart
await page.evaluate(async () => { for (const d of [...window.__srs.S.drawings.values()]) if (d.ticker === 'CSCO') await window.__srs.api.deleteDrawing(d.id); });
await page.waitForTimeout(150);
ok((await page.locator('.card[data-id]').count()) === 0, 'demo TV rows hidden');
await page.tap('#addLong');
await page.touchscreen.tap(chart.x + chart.width * 0.45, chart.y + chart.height * 0.40);
await page.touchscreen.tap(chart.x + chart.width * 0.45, chart.y + chart.height * 0.55);
await page.waitForFunction(() => document.querySelectorAll('.card[data-id]').length === 1);
await page.waitForTimeout(2800); // toast fade
const L = () => page.evaluate(() => { const s = window.__srs; return { ...[...s.S.drawings.values()].find((d) => d.kind === 'long' && d.source === 'user' && d.status !== 'deleted') }; });
const long0 = await L();
ok(long0.t_start && long0.t_end && long0.t_end > long0.t_start, `new long stores time anchor t_start=${long0.t_start} t_end=${long0.t_end}`);

// ---- 3. SL size label ----
const slTxt = () => page.locator('g.slsz text').first().textContent();
const expSl = (d) => `SL $${(d.entry - d.stop).toFixed(2)} (${((d.entry - d.stop) / d.entry * 100).toFixed(1)}%)`;
ok((await slTxt()) === expSl(long0), `SL label "${await slTxt()}"`);
await shot('03_long_selected_sl_label');

// ---- 4. dashed guide during touch drag of SL ----
const sh = await page.locator('g.h[data-key="stop"] circle').nth(1).boundingBox();
const sx = sh.x + sh.width / 2, sy = sh.y + sh.height / 2;
ok((await page.locator('g.dragguide').count()) === 0, 'no guide before drag');
await touch('touchStart', sx, sy);
for (let i = 1; i <= 6; i++) { await touch('touchMove', sx, sy + i * 6); await page.waitForTimeout(16); }
await page.waitForTimeout(80);
const g = await page.evaluate(() => { const l = document.querySelector('g.dragguide line'); return l && { x1: +l.getAttribute('x1'), x2: +l.getAttribute('x2'), dash: l.getAttribute('stroke-dasharray'), W: window.__srs.cv.chart.timeScale().width() }; });
ok(g && g.x1 === 0 && Math.abs(g.x2 - g.W) < 1 && g.dash, `dashed guide across full width while dragging SL (touch) ${JSON.stringify(g)}`);
const LV = () => page.evaluate(() => ({ ...window.__srs.cv.drawings.find((d) => d.kind === 'long' && d.source === 'user') })); // live drag copy
const mid = await LV();
const midLbl = await slTxt();
ok(midLbl === expSl(mid) && mid.stop < long0.stop, `SL label live during drag: "${midLbl}" (stop ${long0.stop} -> ${mid.stop})`);
await shot('04_dragging_sl_dashed_guide');
await touch('touchEnd'); await page.waitForTimeout(150);
ok((await page.locator('g.dragguide').count()) === 0, 'guide removed after touch release');
await shot('05_after_release_no_guide');

// mouse drag of Entry: guide + live SL label, gone after mouseup
const eh = await page.locator('g.h[data-key="entry"] circle').nth(1).boundingBox();
await page.mouse.move(eh.x + eh.width / 2, eh.y + eh.height / 2); await page.mouse.down();
await page.mouse.move(eh.x + eh.width / 2, eh.y - 15, { steps: 4 }); await page.waitForTimeout(60);
const midE = await LV();
ok((await page.locator('g.dragguide').count()) === 1 && (await slTxt()) === expSl(midE), `mouse drag Entry: guide shown, SL label "${await slTxt()}"`);
await page.mouse.up(); await page.waitForTimeout(120);
ok((await page.locator('g.dragguide').count()) === 0, 'guide removed after mouseup');
const saved = await page.evaluate(() => window.__demoApi.drawings.find((d) => d.kind === 'long' && d.source === 'user' && d.status !== 'deleted'));
ok(saved.t_start === long0.t_start && saved.t_end === long0.t_end && saved.entry > long0.entry, `drag persisted entry ${long0.entry} -> ${saved.entry}, anchor unchanged ${saved.t_start}..${saved.t_end}`);
// time handle: drag t_start moves the whole position by bars, width kept
const span = () => page.evaluate(() => { const cv = window.__srs.cv; const d = cv.drawings.find((x) => x.kind === 'long' && x.source === 'user'); return [cv.logicalOf(d.t_start), cv.logicalOf(d.t_end)]; });
const sp0 = await span();
const th = await page.locator('g.h[data-key="t_start"] rect').nth(1).boundingBox();
await page.mouse.move(th.x + th.width / 2, th.y + th.height / 2); await page.mouse.down();
await page.mouse.move(th.x + th.width / 2 + 21, th.y + th.height / 2, { steps: 4 }); await page.mouse.up(); await page.waitForTimeout(150);
const sp1 = await span();
ok(sp1[0] - sp0[0] >= 2 && sp1[1] - sp1[0] === sp0[1] - sp0[0], `drag start handle moves the position in time: bars ${sp0} -> ${sp1}`);

// ---- 5. sticky: pan / zoom keep the long glued to its candles ----
const geo = () => page.evaluate(() => {
  const cv = window.__srs.cv; const d = [...window.__srs.S.drawings.values()].find((x) => x.kind === 'long' && x.source === 'user' && x.status !== 'deleted');
  const r = [...document.querySelectorAll('svg.overlay rect')].find((e) => e.getAttribute('stroke') === '#26a69a');
  const ts = cv.chart.timeScale();
  return { boxX: r ? +r.getAttribute('x') : null, boxW: r ? +r.getAttribute('width') : null,
    candleX: ts.logicalToCoordinate(cv.logicalOf(d.t_start)), endX: ts.logicalToCoordinate(cv.logicalOf(d.t_end)) };
});
// deselect so handles do not catch the pan gesture
await page.locator('.card[data-id] .selbtn').first().tap(); await page.waitForTimeout(2800);
const g0 = await geo();
await shot('06_sticky_before_pan');
const py = chart.y + chart.height * 0.15, px = chart.x + chart.width * 0.7;
await touch('touchStart', px, py);
for (let i = 1; i <= 10; i++) { await touch('touchMove', px - i * 12, py); await page.waitForTimeout(16); }
await touch('touchEnd'); await page.waitForTimeout(500);
const g1 = await geo();
ok(Math.abs(g1.boxX - g0.boxX) > 30, `pan moved the long with the chart: x ${g0.boxX.toFixed(1)} -> ${g1.boxX.toFixed(1)}`);
ok(Math.abs(g1.boxX - Math.max(-2, g1.candleX)) < 1.5, `long left edge still on its t_start candle (${g1.boxX.toFixed(1)} vs ${g1.candleX.toFixed(1)})`);
await shot('07_sticky_after_pan');
await page.evaluate(() => { const ts = window.__srs.cv.chart.timeScale(); const r = ts.getVisibleLogicalRange(); const c = (r.from + r.to) / 2, h = (r.to - r.from) / 4; ts.setVisibleLogicalRange({ from: c - h, to: c + h }); });
await page.waitForTimeout(400);
const g2 = await geo();
ok(Math.abs(g2.boxX - Math.max(-2, g2.candleX)) < 1.5 && g2.boxW > g1.boxW * 1.5, `zoom in: box scaled with bars (width ${g1.boxW.toFixed(1)} -> ${g2.boxW.toFixed(1)}), left edge on candle`);
await shot('08_sticky_after_zoom');

// ---- 6. legacy TV long without anchors: right of the last candle, no write until edited ----
await page.reload(); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(800);
const leg = await page.evaluate(() => {
  const cv = window.__srs.cv; const d = [...window.__srs.S.drawings.values()].find((x) => x.kind === 'long' && x.source === 'tv');
  const r = [...document.querySelectorAll('svg.overlay rect')].find((e) => e.getAttribute('stroke') === '#26a69a');
  return { t_start: d.t_start, t_end: d.t_end, boxX: r && +r.getAttribute('x'), lastX: cv.chart.timeScale().logicalToCoordinate(cv.bars.length - 1) };
});
ok(leg.t_start == null && leg.t_end == null && leg.boxX > leg.lastX, `legacy long (no anchor) drawn right of last candle (${leg.boxX?.toFixed(1)} > ${leg.lastX.toFixed(1)}), not rewritten`);
await shot('09_legacy_tv_long');

ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
