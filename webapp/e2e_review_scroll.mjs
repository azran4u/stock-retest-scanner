// Regression (Eyal 2026-10-31: "the review area is small and can't be scrolled"): the stock overview 'סקירה' must be
// readable to its last line on every layout - split view (laptop 1024 / 1366, iPad portrait 820 + landscape 1180) and
// phone (390). Desktop: mouse wheel over the panel; touch: a real finger drag (CDP Input.dispatchTouchEvent).
// Also: the review is never a tiny inner scroller, the chart keeps its height, the side list scrolls on its own.
// Usage: node e2e_review_scroll.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/review_scroll';
mkdirSync(OUT, { recursive: true });
const RES = JSON.parse(readFileSync(new URL('./e2e_research.fixture.json', import.meta.url)));
RES[0].summary_he = Array.from({ length: 30 }, (_, i) => `נושא ${i + 1}: שורה ארוכה של סקירה כדי לבדוק גלילה באזור הסקירה, עם עוד טקסט שישבור שורה`).join('\n') + '\nסוף: השורה האחרונה של הסקירה';
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
async function swipe(cdp, x, y, dy) { // finger drag up by dy px (content moves up = scroll down)
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
  for (let i = 1; i <= 10; i++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y - (dy * i) / 10 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
}
const lastVisible = (p) => p.locator('#research .rs-body p').last().evaluate((e) => {
  const r = e.getBoundingClientRect(); const pane = e.closest('.smain'); const top = pane ? pane.getBoundingClientRect().top : 0;
  return r.top >= top && r.bottom <= innerHeight && r.height > 0;
});
for (const [name, vp, touch, split] of [
  ['laptop_1024x768', { width: 1024, height: 768 }, false, true],
  ['laptop_1366x768', { width: 1366, height: 768 }, false, true],
  ['ipad_portrait_820x1180', { width: 820, height: 1180 }, true, true],
  ['ipad_landscape_1180x820', { width: 1180, height: 820 }, true, true],
  ['iphone_390x844', { width: 390, height: 844 }, true, false],
]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 1, isMobile: touch, hasTouch: touch, locale: 'he-IL' });
  await ctx.addInitScript((r) => { window.__demoResearch = r; localStorage.clear(); }, RES);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/t/CSCO');
  await page.waitForSelector('#research .rs-body p'); await page.waitForTimeout(500);
  ok(!!(await page.$('.split')) === split, `${name}: layout ${split ? 'split' : 'single page'}`);
  const m = await page.evaluate(() => {
    const rs = document.querySelector('#research'), pn = document.querySelector('#panel'), cw = document.querySelector('.chartwrap');
    return { rsClip: rs.scrollHeight - rs.clientHeight, pnClip: pn.scrollHeight - pn.clientHeight, chart: cw.getBoundingClientRect().height };
  });
  ok(m.rsClip <= 2 && m.pnClip <= 2, `${name}: review / panel shown at full height, no tiny inner scroller (${m.rsClip}, ${m.pnClip})`);
  ok(m.chart >= 280, `${name}: chart height ${Math.round(m.chart)}px`);
  ok(!(await lastVisible(page)), `${name}: long review's last line starts below the fold`);
  let seen = false;
  if (touch) {
    const cdp = await ctx.newCDPSession(page);
    const box = await page.locator('#panel').boundingBox();
    const x = Math.round(box.x + box.width / 2), y = Math.round(Math.min(vp.height - 60, Math.max(box.y + 30, vp.height * 0.8)));
    for (let i = 0; i < 25 && !seen; i++) {
      await swipe(cdp, x, y, 250);
      await page.waitForTimeout(120); seen = await lastVisible(page);
    }
  } else {
    const box = await page.locator('#panel').boundingBox();
    await page.mouse.move(box.x + box.width / 2, Math.min(vp.height - 30, box.y + 40));
    for (let i = 0; i < 40 && !seen; i++) { await page.mouse.wheel(0, 120); await page.waitForTimeout(60); seen = await lastVisible(page); }
  }
  ok(seen, `${name}: ${touch ? 'touch swipe' : 'mouse wheel'} brings the review's last line into view`);
  ok(await page.locator('header.ch').evaluate((e) => { const r = e.getBoundingClientRect(); return r.top >= -1 && r.top < 80; }), `${name}: stock header stays on top while scrolling`);
  await page.screenshot({ path: `${OUT}/after_${name}_scrolled.png` });
  if (split) { // the side list still scrolls on its own and the pane did not move it
    const lst = page.locator('.side .list'); const lb = await lst.boundingBox();
    const s0 = await lst.evaluate((e) => e.scrollTop);
    if (touch) { const cdp = await ctx.newCDPSession(page); await swipe(cdp, Math.round(lb.x + lb.width / 2), Math.round(lb.y + lb.height * 0.7), 300); }
    else { await page.mouse.move(lb.x + lb.width / 2, lb.y + lb.height / 2); await page.mouse.wheel(0, 400); }
    await page.waitForTimeout(300);
    ok((await lst.evaluate((e) => e.scrollTop)) > s0, `${name}: side list scrolls independently`);
  }
  await ctx.close();
}
ok(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);
await browser.close();
