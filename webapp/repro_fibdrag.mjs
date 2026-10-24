// Reproduce "can't drag the Fibonacci" with real mouse events. Usage: node repro_fibdrag.mjs [baseURL] [browser]
import { chromium, webkit } from 'playwright';
const BASE = process.argv[2] || 'https://azran4u.github.io/stock-retest-scanner/app/';
const B = (process.argv[3] || 'chromium') === 'webkit' ? webkit : chromium;
const browser = await B.launch();
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
await page.goto(BASE + '?demo=1#/t/QCOM'); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(800);
await page.click('#indbar [data-fib]'); await page.waitForTimeout(400);
const st = () => page.evaluate(() => { const b = document.querySelector('.fibbox'); return { low: +b.dataset.fibLow, high: +b.dataset.fibHigh, manual: b.dataset.fibManual, handles: document.querySelectorAll('g.fh').length, range: JSON.stringify(window.__srs.cv.chart.timeScale().getVisibleLogicalRange()) }; });
console.log('fib on, no edit mode:', await st());
// try to grab the Fib 0 (high) line and drag it 5 candles left / up
const pos = await page.evaluate(() => { const cv = window.__srs.cv, r = document.querySelector('#chart').getBoundingClientRect(); const p = cv.fibLines[0].options().price; return { x: r.left + cv.chart.timeScale().width() * 0.85, y: r.top + cv.candles.priceToCoordinate(p) }; });
await page.mouse.move(pos.x, pos.y); await page.mouse.down(); await page.mouse.move(pos.x - 80, pos.y - 30, { steps: 10 }); await page.mouse.up(); await page.waitForTimeout(400);
console.log('after dragging the Fib 0 line:', await st());
// edit mode, drag the high handle
await page.click('#fibEdit'); await page.waitForTimeout(400);
console.log('edit mode:', await st());
const h = await page.locator('g.fh[data-fk="high"] circle').nth(1).boundingBox().catch(() => null);
console.log('high handle box', h);
if (h) {
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2); await page.mouse.down(); await page.mouse.move(h.x - 60, h.y + 10, { steps: 10 }); await page.mouse.up(); await page.waitForTimeout(500);
  console.log('after dragging the high handle in edit mode:', await st());
}
await browser.close();
