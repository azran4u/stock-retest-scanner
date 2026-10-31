// 'Reversal candle that touches the level' filters (Eyal 2026-10-31): revWZ (weekly, last X completed weeks, default 2)
// and revDZ (daily, last X trading days, default 5), with the reversal-kinds picker; level = the zone that counts now
// (app zone, else the exported TV zone); touch = report_filters._scan_reversals gate (low <= top + 0.5 ATR and
// (low >= bottom - 0.5 ATR or close >= bottom)); no zone -> fails. revD / revW unchanged. A zone edited in the app is
// followed live. Demo mode, iPhone 390 + laptop 1366 (split). Usage: node e2e_rev_zone.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/rev_zone';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const KINDS = ['hammer', 'engulfing', 'strong_close', 'rejection'];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.evaluate(() => localStorage.removeItem('srs-app-v1'));
  await page.reload(); await page.waitForSelector('.row');
  const shown = () => page.evaluate(() => +document.querySelector('.sortrow .small').textContent.match(/\d+/)[0]);
  const rowsShown = () => page.$$eval('.row', (els) => els.map((e) => e.dataset.t));
  const on = async (id) => { await page.locator(`.fi[data-f="${id}"] input[type=checkbox]`).click(); await page.waitForTimeout(200); };
  const setX = async (id, v) => { await page.locator(`.fi[data-f="${id}"] .fx`).fill(String(v)); await page.waitForTimeout(200); };
  // independent expectation, computed in the page from revc.json + the live zone (not via filters.ts)
  const expect = (key, x, kinds) => page.evaluate(async ({ key, x, kinds, KINDS }) => {
    const { S, factsOf, liveZoneOf } = window.__srs;
    const rc = await (await fetch('data/revc.json')).json();
    const want = kinds.reduce((m, k) => m | (1 << KINDS.indexOf(k)), 0);
    return S.rows.filter((r) => !factsOf(r).unfit).filter((r) => {
      const z = liveZoneOf(r.ticker, r); if (!z) return false;
      return ((rc[r.ticker] || {})[key] || []).some(([k, m, lo, cl, a]) => k < x && (m & want) && lo <= z.top + 0.5 * a && (lo >= z.bottom - 0.5 * a || cl >= z.bottom));
    }).map((r) => r.ticker).sort();
  }, { key, x, kinds, KINDS });
  await page.locator('#ftog').click();
  for (const [id, lbl, unit, def, max] of [['revWZ', 'נר היפוך שבועי שנוגע ברמה ב-', 'שבועות אחרונים', '2', '26'], ['revDZ', 'נר היפוך יומי שנוגע ברמה ב-', 'ימים אחרונים', '5', '60']]) {
    const fi = page.locator(`.fi[data-f="${id}"]`);
    const txt = await fi.textContent();
    ok(txt.includes(lbl) && txt.includes(unit), `${name}: ${id} listed with its Hebrew label + unit`);
    ok(await fi.locator('.fx').inputValue() === def && await fi.locator('.fx').getAttribute('max') === max, `${name}: ${id} default ${def}, max ${max}`);
    ok(await fi.locator('.kd').count() === 4, `${name}: ${id} has the reversal-kinds picker`);
  }
  // weekly, default 2 weeks, default kinds (hammer + engulfing)
  await on('revWZ');
  await page.waitForFunction(() => window.__srs.revc != null);
  await page.waitForTimeout(300);
  let want = await expect('w', 2, ['hammer', 'engulfing']);
  let got = (await rowsShown()).sort();
  ok(want.length > 0 && JSON.stringify(got) === JSON.stringify(want) && await shown() === want.length, `${name}: weekly touching the level, 2 weeks -> ${want.length} (${want.slice(0, 6).join(' ')})`);
  if (name === 'iphone_390') console.log(`     default counts: weekly 2w = ${want.length}`);
  ok(await page.evaluate((ts) => ts.every((t) => window.__srs.liveZoneOf(t, window.__srs.S.byT.get(t)) != null), got), `${name}: every match has a zone`);
  await page.screenshot({ path: `${OUT}/${name}_weekly_2w.png` });
  await setX('revWZ', 8);
  want = await expect('w', 8, ['hammer', 'engulfing']); got = (await rowsShown()).sort();
  ok(JSON.stringify(got) === JSON.stringify(want), `${name}: weekly 8 weeks -> ${want.length}`);
  await page.locator('.fi[data-f="revWZ"] .kd[data-k="strong_close"]').click(); await page.waitForTimeout(200);
  want = await expect('w', 8, ['hammer', 'engulfing', 'strong_close']); got = (await rowsShown()).sort();
  ok(JSON.stringify(got) === JSON.stringify(want), `${name}: + strong close -> ${want.length}`);
  await on('revWZ');
  // daily, default 5 days
  await on('revDZ');
  want = await expect('d', 5, ['hammer', 'engulfing']); got = (await rowsShown()).sort();
  ok(want.length > 0 && JSON.stringify(got) === JSON.stringify(want), `${name}: daily touching the level, 5 days -> ${want.length}`);
  if (name === 'iphone_390') console.log(`     default counts: daily 5d = ${want.length}`);
  await page.screenshot({ path: `${OUT}/${name}_daily_5d.png` });
  await setX('revDZ', 20);
  want = await expect('d', 20, ['hammer', 'engulfing']); got = (await rowsShown()).sort();
  ok(JSON.stringify(got) === JSON.stringify(want), `${name}: daily 20 days -> ${want.length}`);
  // follows a zone edited in the app: a stock with a recent daily hammer/engulfing NOT at its zone gets an app zone
  // right at that candle's low -> appears; zone moved far away -> disappears
  const cand = await page.evaluate(() => {
    const { S, liveZoneOf } = window.__srs; const rc = window.__srs.revc;
    for (const r of S.rows) {
      const c = ((rc[r.ticker] || {}).d || []).find(([k, m]) => k < 20 && (m & 3));
      if (!c || !r.has_candles) continue;
      const z = liveZoneOf(r.ticker, r);
      const touch = z && ((rc[r.ticker].d || []).some(([k, m, lo, cl, a]) => k < 20 && (m & 3) && lo <= z.top + 0.5 * a && (lo >= z.bottom - 0.5 * a || cl >= z.bottom)));
      if (!touch) return { t: r.ticker, lo: c[2], a: c[4] };
    }
    return null;
  });
  ok(!!cand, `${name}: found a stock with a daily reversal not at its level (${cand?.t})`);
  ok(!(await rowsShown()).includes(cand.t), `${name}: ${cand.t} not listed before the edit`);
  const zid = await page.evaluate(async (c) => {
    const { S, api } = window.__srs;
    const z = await api.insertDrawing({ ticker: c.t, kind: 'zone', zone_top: +(c.lo + 0.2 * c.a).toFixed(2), zone_bottom: +(c.lo - 0.2 * c.a).toFixed(2), source: 'user', status: 'active' });
    S.drawings.set(z.id, z); return z.id;
  }, cand);
  await page.fill('#q', cand.t); await page.waitForTimeout(250);
  ok((await rowsShown()).includes(cand.t), `${name}: app zone drawn at the candle -> ${cand.t} listed (live)`);
  await page.evaluate(({ id, lo }) => { const d = window.__srs.S.drawings.get(id); d.zone_top = +(lo * 0.5).toFixed(2); d.zone_bottom = +(lo * 0.45).toFixed(2); }, { id: zid, lo: cand.lo });
  await page.fill('#q', ''); await page.fill('#q', cand.t); await page.waitForTimeout(250);
  ok(!(await rowsShown()).includes(cand.t), `${name}: zone moved away -> ${cand.t} gone`);
  await page.evaluate((id) => window.__srs.S.drawings.delete(id), zid);   // demo drawing only
  await page.fill('#q', '');
  await on('revDZ');
  // the old filters still work the same (no zone gate)
  await on('revW');
  const F = await page.evaluate(() => window.__srs.S.rows.filter((r) => !window.__srs.factsOf(r).unfit).map((r) => ({ t: r.ticker, ...window.__srs.factsOf(r) })));
  const from = new Date(F[0].today + 'T00:00:00Z'); from.setUTCDate(from.getUTCDate() - 14); const s = from.toISOString().slice(0, 10);
  const wOld = F.filter((f) => ['hammer', 'engulfing'].some((k) => f.revW[k] && f.revW[k] >= s)).length;
  ok(await shown() === wOld, `${name}: old weekly filter (no zone gate) unchanged -> ${wOld}`);
  await on('revW');
  await ctx.close();
}
ok(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);
await browser.close();
