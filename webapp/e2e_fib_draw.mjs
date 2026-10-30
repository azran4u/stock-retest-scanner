// Fib drawing tool (Eyal 2026-10-30, like TradingView): '+ פיבו' -> press on the chart = first anchor (low), drag,
// release = second anchor (target); no automatic placement, no snapping (anchors = raw price / bar time under the
// pointer); the chart does not pan and the page does not scroll while drawing; the drawn Fib can still be edited by
// dragging its end dot (again raw, no snap). Laptop (mouse, split view), iPad (touch, split view), iPhone (touch).
// Usage: node e2e_fib_draw.mjs [baseURL] [outDir] [ticker]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/fib_draw';
const T = process.argv[4] || 'QCOM';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];

for (const [name, vp, mobile] of [['laptop_mouse', { width: 1440, height: 900 }, false], ['ipad_touch', { width: 820, height: 1180 }, true], ['iphone_touch', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`));
  await page.goto(BASE + '?demo=1#/t/' + T);
  await page.waitForSelector('#chart canvas'); await page.waitForTimeout(1200);
  const cdp = mobile ? await ctx.newCDPSession(page) : null;
  const touch = (type, x, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] });
  const drag = async (from, to) => {
    if (!mobile) { await page.mouse.move(from.x, from.y); await page.mouse.down(); await page.mouse.move(to.x, to.y, { steps: 12 }); await page.mouse.up(); }
    else { await touch('touchStart', from.x, from.y); for (let k = 1; k <= 12; k++) await touch('touchMove', from.x + (to.x - from.x) * k / 12, from.y + (to.y - from.y) * k / 12); await touch('touchEnd'); }
    await page.waitForTimeout(500);
  };
  const tap = async (p) => { if (!mobile) await page.mouse.click(p.x, p.y); else { await touch('touchStart', p.x, p.y); await touch('touchEnd'); } await page.waitForTimeout(300); };
  // raw chart value under a page point (what the anchor must be: no snapping)
  const at = (p) => page.evaluate(({ x, y }) => { const cv = window.__srs.cv, r = document.querySelector('#chart').getBoundingClientRect();
    return { time: cv.dateAt(x - r.left), price: cv.priceAt(y - r.top) }; }, p);
  const geo = () => page.evaluate(() => { const cv = window.__srs.cv, r = document.querySelector('#chart').getBoundingClientRect();
    return { left: r.left, top: r.top, W: cv.chart.timeScale().width(), H: cv.chart.paneSize(0).height, range: JSON.stringify(cv.chart.timeScale().getVisibleLogicalRange()) }; });
  const manual = () => page.evaluate((t) => window.__srs.fibManual(t), T);
  const wickAt = (time) => page.evaluate((t) => { const b = window.__srs.cv.bars.find((x) => x.time === t); return b ? [b.low, b.high, b.open, b.close] : []; }, time);

  ok(await manual() === null && (await page.evaluate(() => window.__srs.cv.fibLines.length)) === 0, `${name}: no Fib before drawing (no auto placement)`);
  ok(await page.locator('#addFib').isVisible(), `${name}: '+ פיבו' tool button`);
  if (mobile) await page.locator('#addFib').tap(); else await page.click('#addFib');
  await page.waitForTimeout(200);
  ok(await page.locator('#hint').isVisible() && /פיבונאצי/.test(await page.locator('#hint').textContent()), `${name}: hint shown while the tool is on`);
  let g = await geo();
  const scroll0 = await page.evaluate(() => [window.scrollY, document.querySelector('#main')?.scrollTop ?? 0, document.querySelector('#panel')?.scrollTop ?? 0].join(','));
  const p1 = { x: g.left + g.W * 0.33 + 0.4, y: g.top + g.H * 0.72 + 0.3 }, p2 = { x: g.left + g.W * 0.62 + 0.4, y: g.top + g.H * 0.22 + 0.3 };
  const e1 = await at(p1), e2 = await at(p2);
  await drag(p1, p2);
  const m = await manual();
  ok(m && m.low === e1.price && m.low_date === e1.time && m.high === e2.price && m.high_date === e2.time,
    `${name}: press/drag/release -> Fib low ${m?.low} @ ${m?.low_date}, high ${m?.high} @ ${m?.high_date} (expected ${e1.price} @ ${e1.time} -> ${e2.price} @ ${e2.time})`);
  ok(!(await wickAt(e1.time)).includes(m?.low) && !(await wickAt(e2.time)).includes(m?.high), `${name}: anchors not snapped to the candle OHLC`);
  ok((await geo()).range === g.range, `${name}: the chart did not pan while drawing`);
  ok(await page.evaluate(() => [window.scrollY, document.querySelector('#main')?.scrollTop ?? 0, document.querySelector('#panel')?.scrollTop ?? 0].join(',')) === scroll0, `${name}: the page did not scroll while drawing`);
  const lines = await page.evaluate(() => window.__srs.cv.fibLines.map((p) => p.options().price));
  ok(lines.length === 5 && Math.abs(lines[0] - e2.price) < 1e-9 && Math.abs(lines[4] - e1.price) < 1e-9, `${name}: Fib levels drawn from ${e1.price} to ${e2.price}`);
  ok(await page.locator('#hint').isHidden() && !(await page.evaluate(() => window.__srs.cv.fibDrawing)), `${name}: tool off after the release`);
  await page.screenshot({ path: `${OUT}/${name}_drawn.png` });
  // edit: drag the low end dot -> raw point, no snap
  const dot = await page.evaluate(() => { const c = document.querySelector('g.fh:not(.fl)[data-fk="low"] circle.fhdot'); if (!c) return null; const b = c.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
  ok(!!dot, `${name}: drawn Fib has an editable low dot`);
  if (dot) {
    const to = { x: dot.x - g.W * 0.08 + 0.3, y: dot.y + g.H * 0.06 + 0.2 };
    const e3 = await at(to);
    await drag(dot, to);
    const m2 = await manual();
    ok(m2 && m2.low === e3.price && m2.low_date === e3.time && m2.high === e2.price, `${name}: dragged the low dot -> ${m2?.low} @ ${m2?.low_date} (expected ${e3.price} @ ${e3.time}, no snap), high kept`);
  }
  // click, then click (desktop) / tap, then tap (touch) also draws
  if (mobile) await page.locator('#addFib').tap(); else await page.click('#addFib');
  const q1 = { x: g.left + g.W * 0.45 + 0.2, y: g.top + g.H * 0.65 + 0.1 }, q2 = { x: g.left + g.W * 0.75 + 0.2, y: g.top + g.H * 0.3 + 0.1 };
  const f1 = await at(q1), f2 = await at(q2);
  await tap(q1); await tap(q2); await page.waitForTimeout(300);
  const m3 = await manual();
  ok(m3 && m3.low === f1.price && m3.high === f2.price && m3.low_date === f1.time && m3.high_date === f2.time, `${name}: ${mobile ? 'tap + tap' : 'click + click'} draws ${f1.price} -> ${f2.price}`);
  // persisted: reload shows the same Fib
  await page.reload(); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(1200);
  const m4 = await manual();
  ok(m4 && m4.low === m3.low && m4.high === m3.high && (await page.evaluate(() => window.__srs.cv.fibLines.length)) === 5, `${name}: Fib kept after reload`);
  await page.screenshot({ path: `${OUT}/${name}_after_reload.png` });
  await ctx.close();
}
ok(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);
await browser.close();
