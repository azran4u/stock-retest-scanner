// Manual Fibonacci anchors (Eyal 2026-10-24): no edit button - drag the Fib end lines directly (also from the price-axis
// label) or the end dots, with real mouse / touch events; snap to the nearest wick, persistence, reset to automatic, confluence text. Demo mode. Usage: node e2e_fib_manual.mjs [baseURL] [outDir] [ticker]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
const T = process.argv[4] || 'QCOM';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
// screen point of bar i (logical index of the current timeframe), at mid-candle height
const pt = (page, i) => page.evaluate((i) => {
  const cv = window.__srs.cv, b = cv.bars[i], r = document.querySelector('#chart').getBoundingClientRect();
  return { x: r.left + cv.chart.timeScale().logicalToCoordinate(i), y: r.top + cv.candles.priceToCoordinate((b.high + b.low) / 2), time: b.time, low: b.low, high: b.high };
}, i);
const box = (page) => page.evaluate(() => { const b = document.querySelector('.fibbox'); return { low: +b.dataset.fibLow, high: +b.dataset.fibHigh, manual: b.dataset.fibManual === '1', txt: b.textContent.replace(/\s+/g, ' ') }; });
const lines = (page) => page.evaluate(() => window.__srs.cv.fibLines.map((p) => p.options().price));
const expectConf = (f, price, atr) => { // same rule as indicators.ts
  let best = null; for (const x of [0.382, 0.5, 0.618]) { const d = Math.abs(price - (f.high - x * (f.high - f.low))); if (d <= 0.25 * atr && (!best || d < best[0])) best = [d, x]; } return best ? best[1] : null; };

for (const [name, vp, mobile] of [['desktop_1440', { width: 1440, height: 900 }, false], ['iphone_390', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.goto(BASE + '?demo=1#/t/' + T);
  await page.waitForSelector('#chart canvas'); await page.waitForTimeout(700);
  const auto = await box(page);
  ok(!auto.manual && /אוטומטי/.test(auto.txt), `${name}: automatic anchor ${auto.low} -> ${auto.high}`);
  if (name === 'iphone_390') { await page.click('[data-tf="D"]'); await page.waitForTimeout(500); }
  ok(await page.locator('#fibEdit').count() === 0, `${name}: no "ערוך פיבונאצי" button any more`);
  if (!(await page.evaluate(() => window.__srs.S.ui.fib))) { await page.click('#indbar [data-fib]'); await page.waitForTimeout(400); }
  ok((await lines(page)).length === 5 && await page.locator('g.fh.fl').count() === 2 && await page.locator('g.fh circle.fhdot').count() >= 2, `${name}: Fib on -> both end lines + end dots grabbable right away`);
  // geometry: chart rect, pane width, price-axis width, y of a price, x of a bar
  const geo = () => page.evaluate(() => { const cv = window.__srs.cv, r = document.querySelector('#chart').getBoundingClientRect();
    return { left: r.left, top: r.top, paneW: cv.chart.timeScale().width(), psW: cv.chart.priceScale('right').width(), range: cv.chart.timeScale().getVisibleLogicalRange() }; });
  const yOf = (p) => page.evaluate((p) => window.__srs.cv.candles.priceToCoordinate(p), p);
  // independent expectation: visible candle with the nearest wick to the drop point, keeping low before/below high
  const expectSnap = (which, x, y, wx) => page.evaluate(({ which, x, y, wx }) => {
    const cv = window.__srs.cv, n = cv.bars.length, lr = cv.chart.timeScale().getVisibleLogicalRange();
    const o = cv.fibEdit[which === 'low' ? 'high' : 'low'], oT = o.time, oP = o.price;
    const xc = Math.max(0, Math.min(cv.chart.timeScale().width(), x)); let best = null, bs = Infinity;
    for (let i = Math.max(0, Math.floor(lr.from)); i <= Math.min(n - 1, Math.ceil(lr.to)); i++) {
      const b = cv.bars[i], p = which === 'low' ? b.low : b.high;
      if (which === 'low' ? !(b.time < oT && p < oP) : !(b.time > oT && p > oP)) continue;
      const sc = Math.abs(cv.candles.priceToCoordinate(p) - y) + wx * Math.abs(cv.chart.timeScale().logicalToCoordinate(i) - xc);
      if (sc < bs) { bs = sc; best = { time: b.time, price: p }; }
    }
    return best; }, { which, x, y, wx });
  // drag helpers: real mouse events on desktop, real touch events (CDP) on the iPhone
  const cdp = mobile ? await ctx.newCDPSession(page) : null;
  const touch = (type, x, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] });
  const drag = async (from, to, hold) => {
    if (!mobile) { await page.mouse.move(from.x, from.y); await page.mouse.down(); await page.mouse.move(to.x, to.y, { steps: 10 }); if (hold) await hold(); await page.mouse.up(); }
    else { await touch('touchStart', from.x, from.y); for (let k = 1; k <= 10; k++) await touch('touchMove', from.x + (to.x - from.x) * k / 10, from.y + (to.y - from.y) * k / 10); if (hold) await hold(); await touch('touchEnd'); }
    await page.waitForTimeout(450);
  };
  let g = await geo();
  const n = await page.evaluate(() => window.__srs.cv.bars.length);
  // 1) grab the LOW end line from the side - on the price axis where its label sits - and drag it to a lower candle low
  let f0 = await box(page);
  const yLow = await yOf(f0.low);
  const axisX = g.left + g.paneW + g.psW / 2;
  if (!mobile) {
    await page.mouse.move(axisX, g.top + yLow);
    const cur = await page.evaluate(({ x, y }) => { const el = document.elementFromPoint(x, y); return el && getComputedStyle(el).cursor; }, { x: axisX, y: g.top + yLow });
    ok(cur === 'ns-resize', `hover over the Fib low label on the price axis -> cursor ${cur}`);
  }
  const lowTarget = await page.evaluate(({ hd }) => { const cv = window.__srs.cv, lr = cv.chart.timeScale().getVisibleLogicalRange();
    const c = cv.bars.map((b, i) => ({ b, i })).filter(({ b, i }) => i >= Math.ceil(lr.from) + 2 && b.time < hd); return c.length ? c[Math.floor(c.length / 3)].b : null; }, { hd: f0.high_date || '9999' });
  const yT = (await yOf(lowTarget ? lowTarget.low : f0.low * 0.97)) + 3;
  const exp1 = await expectSnap('low', g.paneW + g.psW / 2, yT, 0.15);
  const rng0 = g.range;
  await drag({ x: axisX, y: g.top + yLow }, { x: axisX, y: g.top + yT }, !mobile ? async () => {
    await page.screenshot({ path: `${OUT}/51_fib_drag_${T}_${name}.png` }); console.log('     shot (mid-drag)', `${OUT}/51_fib_drag_${T}_${name}.png`);
  } : async () => { await page.screenshot({ path: `${OUT}/51_fib_drag_${T}_${name}.png` }); console.log('     shot (mid-drag)', `${OUT}/51_fib_drag_${T}_${name}.png`); });
  let b = await box(page);
  ok(b.manual && exp1 && b.low === exp1.price && /ידני/.test(b.txt), `${name}: dragged the low line from the price-axis label (${mobile ? 'touch' : 'mouse'}) -> snapped to wick ${b.low} (expected nearest wick ${exp1 && exp1.price} @ ${exp1 && exp1.time}), high kept ${b.high}`);
  g = await geo();
  // (right edge fixed; the left edge may move ~1 bar when the price-axis labels change width - that is not a pan)
  ok(Math.abs(g.range.from - rng0.from) <= 1.5 && Math.abs(g.range.to - rng0.to) < 1e-6, `${name}: chart did not pan / scale while dragging ${JSON.stringify(rng0)} ${JSON.stringify(g.range)}`);
  const lab = await page.evaluate((t) => window.__srs.S.labels.filter((l) => l.ticker === t && l.label === 'fib_anchor').map((l) => l.value), T);
  ok(lab.length === 1 && JSON.parse(lab[0]).low === b.low, `${name}: saved as label fib_anchor ${lab[0]}`);
  const L = await lines(page);
  ok(Math.abs(L[2] - (b.high + b.low) / 2) < 1e-6, `${name}: Fib 0.5 line at ${L[2].toFixed(2)}`);
  const px = await page.evaluate(async (t) => { const d = await window.__srs.loadDaily(t); return d[d.length - 1].close; }, T);
  const exp = expectConf(b, px, await page.evaluate(() => window.__srs.fibOfCur().atr_w));
  ok(exp == null ? !b.txt.includes('המחיר ליד פיבו') : b.txt.includes(`המחיר ליד פיבו ${exp}`), `${name}: confluence text follows the dragged anchors (expected price level ${exp})`);
  // 2) grab the HIGH end line in the middle of the chart and drag it up above the current high -> nearest candle high
  const yHigh = await yOf(b.high);
  const midX = g.left + g.paneW * 0.55, yUp = yHigh - 25;
  const exp2 = await expectSnap('high', g.paneW * 0.55, yUp, 0.15);
  await drag({ x: midX, y: g.top + yHigh }, { x: midX, y: g.top + yUp });
  const bh = await box(page);
  ok(exp2 && bh.high === exp2.price && bh.low === b.low, `${name}: dragged the high line inside the chart -> snapped to wick ${bh.high} (expected ${exp2 && exp2.price} @ ${exp2 && exp2.time})`);
  b = bh;
  // 3) end dot: drag the high dot onto a specific candle -> that candle's high
  const dot = await page.locator('g.fh[data-fk="high"] circle.fhdot').boundingBox();
  if (dot) {
    const iT = Math.min(n - 1, Math.max(0, Math.round(g.range.to) - 6));
    const p2 = await pt(page, iT);
    const exp3 = await expectSnap('high', p2.x - g.left, (await yOf(p2.high)), 1);
    await drag({ x: dot.x + dot.width / 2, y: dot.y + dot.height / 2 }, { x: p2.x, y: g.top + (await yOf(p2.high)) });
    b = await box(page);
    ok(exp3 && b.high === exp3.price, `${name}: dragged the high dot onto ${p2.time} -> high ${b.high} (expected ${exp3 && exp3.price} @ ${exp3 && exp3.time})`);
    ok(b.low < b.high, `${name}: low stays before / below the high`);
  } else ok(false, `${name}: high dot visible`);
  await page.screenshot({ path: `${OUT}/50_fib_edit_${T}_${name}.png` });
  console.log('     shot', `${OUT}/50_fib_edit_${T}_${name}.png`);
  const saved = await box(page);
  // persistence: reload -> manual anchors kept (localStorage copy in demo; Supabase label in the real app)
  await page.reload(); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(700);
  b = await box(page);
  ok(b.manual && b.low === saved.low && b.high === saved.high && Math.abs((await lines(page))[2] - (b.low + b.high) / 2) < 1e-6, `${name}: after reload still manual ${b.low} -> ${b.high}, chart lines follow`);
  if (!mobile) {
    // list: card + mini chart use the manual anchors
    const lst = await page.evaluate((t) => { const { S, fibManual } = window.__srs; return fibManual(t); }, T);
    ok(lst && lst.low === saved.low, 'list card / mini chart read the manual anchors (fibManual)');
    await page.click('#back'); await page.waitForSelector('.row'); await page.fill('#q', T); await page.waitForTimeout(300);
    const fl = await page.locator(`.row[data-t="${T}"] .fibline`).count() ? await page.locator(`.row[data-t="${T}"] .fibline`).textContent() : '(no confluence line)';
    console.log('     list card:', fl);
    ok(fl === '(no confluence line)' || fl.includes('(ידני)'), 'list card line marked (ידני)');
    await page.fill('#q', ''); await page.goto(BASE + '?demo=1#/t/' + T); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
  }
  // reset to automatic
  await page.click('#fibAuto'); await page.waitForTimeout(400);
  b = await box(page);
  ok(!b.manual && b.low === auto.low && b.high === auto.high && /אוטומטי/.test(b.txt), `${name}: אפס לאוטומטי -> ${b.low} -> ${b.high}`);
  await page.reload(); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
  ok(!(await box(page)).manual, `${name}: reset survives reload`);
  await ctx.close();
}
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
