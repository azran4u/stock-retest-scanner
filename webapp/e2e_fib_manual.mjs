// Manual Fibonacci anchors (Eyal 2026-10-24): tap / click a candle for the low and the high (snaps to the wick), drag the
// handles, persistence, reset to automatic, confluence text. Demo mode. Usage: node e2e_fib_manual.mjs [baseURL] [outDir] [ticker]
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
  const press = async (p) => (mobile ? page.touchscreen.tap(p.x, p.y) : page.mouse.click(p.x, p.y));
  await page.click('#fibEdit'); await page.waitForTimeout(300);
  ok(/תחילת גל העליות/.test(await page.locator('#hint').textContent()), `${name}: edit mode hint: ${(await page.locator('#fibMsg').textContent()).trim()}`);
  ok((await lines(page)).length === 5, 'Fib turned on with edit mode');
  const n = await page.evaluate(() => window.__srs.cv.bars.length);
  const iLo = n - 40, iHi = n - 12;
  const pLo = await pt(page, iLo);
  await press(pLo); await page.waitForTimeout(300);
  ok(/השיא/.test(await page.locator('#fibMsg').textContent()), `${name}: low tapped (${mobile ? 'touch' : 'click'}) at ${pLo.time}, now asks for the high`);
  const pHi = await pt(page, iHi);
  await press(pHi); await page.waitForTimeout(400);
  let b = await box(page);
  ok(b.manual && b.low === pLo.low && b.high === pHi.high && /ידני/.test(b.txt), `${name}: snapped to wicks: low ${b.low} (= candle low ${pLo.low}), high ${b.high} (= candle high ${pHi.high}), badge ידני`);
  const lab = await page.evaluate((t) => window.__srs.S.labels.filter((l) => l.ticker === t && l.label === 'fib_anchor').map((l) => l.value), T);
  ok(lab.length === 1 && JSON.parse(lab[0]).low === pLo.low, `${name}: saved as label fib_anchor ${lab[0]}`);
  const L = await lines(page);
  ok(Math.abs(L[2] - (b.high + b.low) / 2) < 1e-6, `${name}: Fib 0.5 line at ${L[2].toFixed(2)}`);
  const st = await page.evaluate(() => { const S = window.__srs.S; return { px: S.byT.get(S.ticker).current_price, atr: window.__srs.cv.atrVal }; });
  const px = await page.evaluate(async (t) => { const d = await window.__srs.loadDaily(t); return d[d.length - 1].close; }, T);
  const exp = expectConf(b, px, (await page.evaluate(async (t) => { const { fibOfCur } = window.__srs; return fibOfCur().atr_w; }, T)));
  ok(exp == null ? !b.txt.includes('המחיר ליד פיבו') : b.txt.includes(`המחיר ליד פיבו ${exp}`), `${name}: confluence text follows the manual anchors (expected price level ${exp})`);
  // handles visible in edit mode
  ok(await page.locator('g.fh').count() === 2, `${name}: 2 anchor handles`);
  if (!mobile) {
    // drag the high handle 4 candles left -> snaps to that candle's high
    const h = await page.locator('g.fh[data-fk="high"] circle').nth(1).boundingBox();
    const p2 = await pt(page, iHi - 4);
    await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2); await page.mouse.down();
    await page.mouse.move(p2.x, h.y + 20, { steps: 8 }); await page.mouse.up(); await page.waitForTimeout(400);
    b = await box(page);
    ok(b.high === p2.high && b.low === pLo.low, `drag high handle -> ${p2.time}: high ${b.high} (= candle high ${p2.high})`);
    const exp2 = expectConf(b, px, (await page.evaluate(() => window.__srs.fibOfCur().atr_w)));
    ok(exp2 == null ? !b.txt.includes('המחיר ליד פיבו') : b.txt.includes(`המחיר ליד פיבו ${exp2}`), `confluence text updated after the drag (price level ${exp2}): ${b.txt.match(/המחיר ליד פיבו [\d.]+|האזור מתלכד[^.]*?(?= מידע)/g)}`);
    // reject: high before low
    const p3 = await pt(page, iLo - 5);
    const h2 = await page.locator('g.fh[data-fk="high"] circle').nth(1).boundingBox();
    await page.mouse.move(h2.x + h2.width / 2, h2.y + h2.height / 2); await page.mouse.down();
    await page.mouse.move(p3.x, h2.y, { steps: 8 }); await page.mouse.up(); await page.waitForTimeout(400);
    const b3 = await box(page);
    ok(b3.high === b.high && /השיא חייב להיות אחרי השפל/.test(await page.locator('#toast').textContent()), 'high dragged before the low -> rejected, anchors unchanged');
  }
  await page.screenshot({ path: `${OUT}/50_fib_edit_${T}_${name}.png` });
  console.log('     shot', `${OUT}/50_fib_edit_${T}_${name}.png`);
  const saved = await box(page);
  // persistence: reload -> manual anchors kept (localStorage copy in demo; Supabase label in the real app)
  await page.click('#fibDone'); await page.waitForTimeout(200);
  ok(await page.locator('g.fh').count() === 0 && await page.locator('#hint').isHidden(), `${name}: סיום -> handles gone`);
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
