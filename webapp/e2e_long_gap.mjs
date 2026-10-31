// Long Position box never touches the last candle (Eyal 2026-10-31, VLUE weekly on iPad: "the last candle merges with
// the trade box; move it, on all charts, at least one week from the last candle"). Weekly + daily, bot + his own Long,
// stored anchors overlapping the last candle / no anchors at all: the box's left edge is drawn more than one week of
// bar spacing right of the last candle's right edge, inside the visible pane; the saved t_start / t_end are unchanged.
// Laptop (split), iPad, iPhone. Usage: node e2e_long_gap.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/long_gap';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const T = 'VLUE';
for (const [name, vp, mobile] of [['laptop_1366', { width: 1366, height: 768 }, false], ['ipad_1180', { width: 1180, height: 820 }, true], ['iphone_390', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1'); await page.waitForSelector('.row');
  // his Long anchored ON the last weekly candle + a bot Long without anchors (legacy) -> both must be drawn after the gap
  const ids = await page.evaluate(async (t) => {
    const { S, api, loadDaily } = window.__srs;
    for (const d of [...S.drawings.values()]) if (d.ticker === t && d.kind === 'long') S.drawings.delete(d.id);
    const daily = await loadDaily(t); const last = daily[daily.length - 1]; const c = last.close;
    const mon = (() => { const d = new Date(last.time + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10); })();
    const u = await api.insertDrawing({ ticker: t, kind: 'long', entry: +(c * 0.97).toFixed(2), stop: +(c * 0.93).toFixed(2), target: +(c * 1.06).toFixed(2), t_start: mon, t_end: null, source: 'user', status: 'active' });
    const b = await api.insertDrawing({ ticker: t, kind: 'long', entry: +(c * 0.98).toFixed(2), stop: +(c * 0.94).toFixed(2), target: +(c * 1.1).toFixed(2), source: 'bot', status: 'active' });
    S.drawings.set(u.id, u); S.drawings.set(b.id, b);
    return { u: u.id, b: b.id, saved: { [u.id]: [u.t_start ?? null, u.t_end ?? null], [b.id]: [b.t_start ?? null, b.t_end ?? null] } };
  }, T);
  await page.goto(BASE + `?demo=1#/t/${T}`);
  await page.waitForFunction((t) => window.__srs?.S.ticker === t && window.__srs.cv?.bars.length > 0, T);
  for (const tf of ['W', 'D']) {
    const btn = page.locator(`[data-tf="${tf}"]`);
    if (mobile) await btn.tap(); else await btn.click();
    await page.waitForTimeout(900);
    const g = await page.evaluate(({ ids }) => {
      const cv = window.__srs.cv, ts = cv.chart.timeScale(), n = cv.bars.length, sp = ts.options().barSpacing;
      const W = ts.width();
      const lastRight = ts.logicalToCoordinate(n - 1) + sp / 2;
      // the long boxes: green (entry-target) rects; left edge = x
      const rects = [...document.querySelectorAll('#chart svg rect')].filter((r) => r.getAttribute('fill') === 'rgba(38,166,154,.22)')
        .map((r) => ({ x: +r.getAttribute('x'), w: +r.getAttribute('width') }));
      const spans = Object.fromEntries([ids.u, ids.b].map((id) => [id, cv.longDisplaySpan(cv.drawings.find((d) => d.id === id))]));
      return { n, sp, W, lastRight, rects, spans, weekly: cv.weekly };
    }, { ids });
    const week = g.sp * (g.weekly ? 1 : 5);
    ok(g.rects.length === 2, `${name} ${tf}: both Long boxes drawn (${g.rects.length})`);
    for (const r of g.rects) {
      ok(r.x > g.lastRight + week - 0.5, `${name} ${tf}: box left ${r.x.toFixed(0)} > last candle right ${g.lastRight.toFixed(0)} + 1 week ${week.toFixed(1)}px`);
      ok(r.x < g.W - 20 && r.w >= 20, `${name} ${tf}: box visible in the pane (x ${r.x.toFixed(0)}, w ${r.w.toFixed(0)} of ${g.W.toFixed(0)})`);
    }
    await page.screenshot({ path: `${OUT}/${name}_${tf}.png` });
  }
  const now = await page.evaluate((ids) => { const S = window.__srs.S; return Object.fromEntries(Object.keys(ids.saved).map((id) => [id, [S.drawings.get(id).t_start ?? null, S.drawings.get(id).t_end ?? null]])); }, ids);
  ok(JSON.stringify(now) === JSON.stringify(ids.saved), `${name}: saved t_start / t_end unchanged (display only) ${JSON.stringify(now)}`);
  await ctx.close();
}
ok(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);
await browser.close();
