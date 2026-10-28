// Chart indicators (Eyal 2026-10-24): daily SMA 50/100/150/200 toggles + Fibonacci retracement, demo mode.
// Usage: node e2e_indicators.mjs [baseURL] [outDir] [ticker]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
const T = process.argv[4] || 'QCOM';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const state = (page) => page.evaluate(() => { const cv = window.__srs.cv; return { mas: [...cv.maSeries.keys()], maLen: [...cv.maSeries.values()].map((s) => s.data().length), fib: cv.fibLines.map((p) => p.options().price), legend: document.querySelector('.malegend')?.hidden ? '' : document.querySelector('.malegend')?.textContent || '' }; });

for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['desktop_1440', { width: 1440, height: 900 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.goto(BASE + '?demo=1#/t/' + T);
  await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
  ok(await page.locator('#indbar .chip.ind:not(.earnchip)').count() === 6, `${name}: 6 indicator chips (MA50/100/150/200, כל הממוצעים, פיבונאצי) + דוחות (e2e_earnings)`);
  let st = await state(page);
  ok(st.mas.length === 0 && st.fib.length === 0, `${name}: off by default`);
  if (name === 'iphone_390') {
    await page.click('#indbar [data-ma="50"]'); await page.waitForTimeout(200);
    st = await state(page);
    ok(JSON.stringify(st.mas) === '[50]' && /MA50 \d/.test(st.legend), `MA50 alone: legend "${st.legend}"`);
  }
  await page.click('#indbar [data-ma="all"]'); await page.waitForTimeout(200);
  st = await state(page);
  ok(st.mas.length === 4 && st.legend.includes('MA200'), `${name}: כל הממוצעים -> ${st.mas.join(',')} (legend "${st.legend}")`);
  // weekly MA = daily SMA sampled at the week's last trading day
  const chk = await page.evaluate(async (t) => {
    const { loadDaily, cv } = window.__srs; const d = await loadDaily(t);
    const last = d.slice(-200).reduce((a, b) => a + b.close, 0) / 200;
    const s = cv.maSeries.get(200).data(); return { app: s[s.length - 1].value, exp: last };
  }, T);
  ok(Math.abs(chk.app - chk.exp) < 1e-6, `MA200 last weekly point = daily SMA200 of the last day (${chk.app.toFixed(2)})`);
  await page.click('#indbar [data-fib]'); await page.waitForTimeout(300);
  st = await state(page);
  const row = await page.evaluate((t) => window.__srs.S.byT.get(t), T);
  const exp = [0, 0.382, 0.5, 0.618, 1].map((x) => row.fib_high - x * (row.fib_high - row.fib_low));
  ok(st.fib.length === 5 && st.fib.every((p, i) => Math.abs(p - exp[i]) < 1e-6), `${name}: Fib lines ${st.fib.map((p) => p.toFixed(2)).join(' / ')} (low ${row.fib_low} ${row.fib_low_date} -> high ${row.fib_high} ${row.fib_high_date})`);
  const box = await page.locator('.fibbox').textContent();
  ok(/פיבו/.test(box) && /0\.382/.test(box) && /0\.618/.test(box), `${name}: panel: ${box.replace(/\s+/g, ' ').trim().slice(0, 160)}`);
  if (row.fib_price_level != null) ok(box.includes('המחיר ליד פיבו') && box.includes(String(row.fib_price_level)), `price near Fib ${row.fib_price_level} shown`);
  if (name === 'iphone_390') {
    // persisted
    await page.reload(); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
    st = await state(page);
    ok(st.mas.length === 4 && st.fib.length === 5 && await page.locator('#indbar .chip.on').count() === 6, 'toggles persisted after reload');
    // daily timeframe: MAs on daily data
    await page.click('[data-tf="D"]'); await page.waitForTimeout(400);
    const dl = await page.evaluate(async (t) => (await window.__srs.loadDaily(t)).length, T);
    st = await state(page);
    ok(st.maLen[0] === dl - 49 && st.fib.length === 5, `daily view: MA50 has ${st.maLen[0]} daily points, Fib kept`);
    await page.click('[data-tf="W"]'); await page.waitForTimeout(400);
    // MA100 off -> 3
    await page.click('#indbar [data-ma="100"]'); await page.waitForTimeout(200);
    st = await state(page);
    ok(JSON.stringify(st.mas) === '[50,150,200]' && !(await page.locator('#indbar [data-ma="all"]').getAttribute('class')).includes(' on'), 'MA100 off -> 3 MAs, כל הממוצעים off');
    await page.click('#indbar [data-ma="100"]'); await page.waitForTimeout(300);
    // list card shows the Fib confluence line and mini charts follow the toggles
    await page.click('#back'); await page.waitForSelector('.row');
    await page.fill('#q', T); await page.waitForTimeout(300);
    const fl = await page.locator(`.row[data-t="${T}"] .fibline`).textContent().catch(() => '');
    ok(!row.fib_confluence || /פיבונאצי: .*פיבו/.test(fl), `list card: "${fl}" (export: ${row.fib_confluence})`);
    await page.fill('#q', ''); await page.waitForTimeout(200);
    await page.goto(BASE + '?demo=1#/t/' + T); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(800);
  }
  await page.screenshot({ path: `${OUT}/40_indicators_${T}_${name}.png` });
  console.log('     shot', `${OUT}/40_indicators_${T}_${name}.png`);
  await ctx.close();
}
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
