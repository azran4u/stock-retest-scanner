// List card: proportions on desktop + sector / R:R / $ risk-reward (Eyal 2026-10-24), demo mode.
// Usage: node e2e_sizing.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
async function open(viewport, mobile) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.goto(BASE + '?demo=1');
  await page.waitForSelector('.row');
  await page.waitForFunction(() => [...document.querySelectorAll('canvas.spark')].some((c) => c.dataset.drawn));
  await page.waitForTimeout(300);
  return { ctx, page };
}

// ---- desktop 1440x900: grid of cards, chart not stretched ----
{
  const { ctx, page } = await open({ width: 1440, height: 900 }, false);
  const boxes = await page.evaluate(() => [...document.querySelectorAll('.row')].slice(0, 8).map((li) => { const c = li.querySelector('canvas.spark').getBoundingClientRect(); return { top: li.getBoundingClientRect().top, w: c.width, h: c.height }; }));
  const perRow = boxes.filter((b) => Math.abs(b.top - boxes[0].top) < 2).length;
  ok(perRow >= 3, `desktop: ${perRow} cards per row`);
  const b = boxes[0], ratio = b.w / b.h;
  ok(ratio >= 2 && ratio <= 3.2 && b.w <= 520, `desktop mini chart ${b.w.toFixed(0)}x${b.h.toFixed(0)} (ratio ${ratio.toFixed(2)})`);
  const cvPx = await page.evaluate(() => { const c = document.querySelector('canvas.spark'); const r = c.getBoundingClientRect(); return Math.abs(c.width / c.height - r.width / r.height); });
  ok(cvPx < 0.05, 'canvas backing store matches its box (no stretched pixels)');
  await page.screenshot({ path: `${OUT}/20_list_desktop_1440.png` });
  console.log('     shot', `${OUT}/20_list_desktop_1440.png`);
  // resize -> charts redrawn at the new size
  await page.setViewportSize({ width: 1000, height: 900 }); await page.waitForTimeout(500);
  const d2 = await page.evaluate(() => { const c = document.querySelector('canvas.spark'); const r = c.getBoundingClientRect(); return Math.abs(c.width / c.height - r.width / r.height); });
  ok(d2 < 0.05, 'redrawn after window resize');
  await ctx.close();
}

// ---- iPhone 390x844: unchanged look + sector / sizing ----
{
  const { ctx, page } = await open({ width: 390, height: 844 }, true);
  const cw = await page.locator('canvas.spark').first().boundingBox();
  ok(cw.width > 340 && cw.height >= 110 && cw.height <= 140, `iPhone mini chart ${cw.width.toFixed(0)}x${cw.height.toFixed(0)}`);
  const n = await page.locator('.row').count();
  ok(await page.locator('.row .r4').count() === n && await page.locator('.row .r5').count() === n, `every card has a sector line and a sizing line (${n})`);
  const withSec = await page.locator('.row .r4[data-sector]:not([data-sector=""])').count();
  ok(withSec > 0, `sector shown on ${withSec}/${n} cards`);
  const mr = await page.evaluate(() => window.__srs.maxRiskUsd());
  ok(mr === 50, `default max risk $${mr} (5000 × 1%)`);

  // every 'ok' card's $ numbers = floor(50 / (entry - SL)) etc. from the Long that counts
  const check = await page.evaluate(() => {
    const { S, longLevels } = window.__srs; const bad = []; let good = 0;
    for (const li of document.querySelectorAll('.row')) {
      const r5 = li.querySelector('.r5'); if (r5.dataset.sizing !== 'ok') continue;
      const L = longLevels(S.byT.get(li.dataset.t)); const ps = L.entry - L.stop;
      const sh = Math.floor(50 / ps + 1e-9);
      const exp = { s: sh, r: Math.round(sh * ps * 100) / 100, w: Math.round(sh * (L.target - L.entry) * 100) / 100 };
      if (+r5.dataset.shares !== exp.s || Math.abs(+r5.dataset.risk - exp.r) > 0.005 || Math.abs(+r5.dataset.reward - exp.w) > 0.005 || exp.r > 50) bad.push([li.dataset.t, r5.dataset, exp]);
      else good++;
    }
    return { good, bad: bad.slice(0, 3) };
  });
  ok(check.good > 0 && check.bad.length === 0, `$ numbers match the formula on ${check.good} cards ${JSON.stringify(check.bad)}`);

  // live: edit the Long of a ticker -> card re-computes (same path as live R:R / PASS)
  const t = await page.locator('.row').first().getAttribute('data-t');
  const live = await page.evaluate(async (t) => {
    const { S, api, refreshLive } = window.__srs;
    for (const d of [...S.drawings.values()]) if (d.ticker === t && d.kind === 'long') S.drawings.delete(d.id);
    const px = S.byT.get(t).current_price || 100;
    const e = Math.round(px * 100) / 100, sl = Math.round((e - 4) * 100) / 100, tp = Math.round((e + 12) * 100) / 100;
    const l = await api.insertDrawing({ ticker: t, kind: 'long', entry: e, stop: sl, target: tp, source: 'user', status: 'active' });
    S.drawings.set(l.id, l); refreshLive();
    const a = { ...document.querySelector(`.row[data-t="${t}"] .r5`).dataset, rr: document.querySelector(`.row[data-t="${t}"] .sz-rr`).textContent };
    // stop wider than $50 / share
    l.stop = Math.round((e - 60) * 100) / 100; l.updated_at = new Date().toISOString(); refreshLive();
    const b = { ...document.querySelector(`.row[data-t="${t}"] .r5`).dataset, txt: document.querySelector(`.row[data-t="${t}"] .r5`).textContent };
    l.stop = sl; refreshLive();
    return { a, b };
  }, t);
  ok(live.a.shares === '12' && live.a.risk === '48' && live.a.reward === '144' && /3\.00/.test(live.a.rr), `${t} Long risk $4/share, TP +$12: 12 shares, risk $48, reward $144, ${live.a.rr}`);
  ok(live.b.shares === '0' && live.b.sizing === 'wide' && /סטופ רחב מ-\$50 למניה/.test(live.b.txt), `stop $60 wide -> "${live.b.txt.trim()}"`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${OUT}/21_list_iphone_390.png` });
  console.log('     shot', `${OUT}/21_list_iphone_390.png`);

  // dashboard sizing settings (same origin, srs_sizing_v1) are respected: $10000 × 1% = $100
  await page.evaluate(() => { localStorage.setItem('srs_sizing_v1', JSON.stringify({ account: 10000, riskPct: 1, posPct: 15 })); window.__srs.refreshLive(); });
  const s2 = await page.evaluate((t) => document.querySelector(`.row[data-t="${t}"] .r5`).dataset.shares, t);
  ok(s2 === '25', `settings $10000 × 1% -> 25 shares at $4/share risk`);
  await page.evaluate(() => localStorage.removeItem('srs_sizing_v1'));
  await ctx.close();
}
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
