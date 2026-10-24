// Sort by proximity to the zone (Eyal 2026-10-24), demo mode. Usage: node e2e_zone_sort.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const order = (page) => page.evaluate(() => [...document.querySelectorAll('.row')].map((li) => ({ t: li.dataset.t, d: li.querySelector('.r6').dataset.zdist })));

for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['desktop_1440', { width: 1440, height: 900 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.goto(BASE + '?demo=1');
  await page.waitForSelector('.row');
  ok(await page.locator('label.sortlab:has-text("מיון") select#sort option[value="zone"]').textContent() === 'קרבה לאזור', `${name}: sort control 'מיון' has 'קרבה לאזור'`);
  await page.selectOption('#sort', 'zone');
  await page.waitForTimeout(300);
  const o = await order(page);
  const ds = o.map((x) => (x.d === '' ? Infinity : +x.d));
  const firstNone = ds.indexOf(Infinity);
  ok(ds.every((d, i) => i === 0 || ds[i - 1] <= d), `${name}: ${o.length} rows sorted closest first, no-zone last (first no-zone at #${firstNone})`);
  ok(firstNone === -1 || ds.slice(firstNone).every((d) => d === Infinity), 'all no-zone rows are at the end');
  const n6 = await page.locator('.row .r6').count();
  ok(n6 === o.length && /מרחק מהאזור: \d+\.\d ATR/.test(await page.locator('.row .r6').first().textContent()), `${name}: every card shows 'מרחק מהאזור' (${await page.locator('.row .r6').first().textContent()})`);
  // value check vs formula on the top rows
  const chk = await page.evaluate(() => {
    const { S } = window.__srs; const bad = [];
    for (const li of [...document.querySelectorAll('.row')].slice(0, 20)) {
      const r = S.byT.get(li.dataset.t); if (!r) continue;
      const z = [...S.drawings.values()].filter((d) => d.ticker === r.ticker && d.kind === 'zone' && (d.status === 'active' || d.status === 'approved'))
        .sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')))[0];
      const top = Math.max(+(z ? z.zone_top : r.tv_zone_top), +(z ? z.zone_bottom : r.tv_zone_bottom)), bot = Math.min(+(z ? z.zone_top : r.tv_zone_top), +(z ? z.zone_bottom : r.tv_zone_bottom));
      const p = r.current_price, exp = (p > top ? p - top : p < bot ? bot - p : 0) / r.weekly_atr;
      if (Math.abs(exp - +li.querySelector('.r6').dataset.zdist) > 1e-3) bad.push([r.ticker, exp, li.querySelector('.r6').dataset.zdist]);
    }
    return bad;
  });
  ok(chk.length === 0, `${name}: distances = |price − nearest zone edge| / weekly ATR ${JSON.stringify(chk)}`);
  if (name === 'iphone_390') {
    console.log('     top5', JSON.stringify(o.slice(0, 5).map((x) => `${x.t} ${(+x.d).toFixed(2)}`)));
    // persisted
    await page.reload(); await page.waitForSelector('.row');
    ok(await page.$eval('#sort', (s) => s.value) === 'zone', 'chosen sort persisted after reload');
    // live: move the last zoned row's zone to straddle the price -> it jumps to the top with 0.0
    const t = o.filter((x) => x.d !== '').at(-1).t;
    await page.evaluate(async (t) => {
      const { S, api, refreshLive } = window.__srs;
      const p = S.byT.get(t).current_price;
      const z = await api.insertDrawing({ ticker: t, kind: 'zone', zone_top: Math.round(p * 1.01 * 100) / 100, zone_bottom: Math.round(p * 0.99 * 100) / 100, source: 'user', status: 'active' });
      z.updated_at = new Date(Date.now() + 1000).toISOString();
      S.drawings.set(z.id, z); refreshLive();
    }, t);
    const o2 = await order(page);
    ok(+o2.find((x) => x.t === t).d === 0 && +o2[0].d === 0 && o2.findIndex((x) => x.t === t) < o2.findIndex((x) => +x.d > 0), `live zone edit: ${t} (was farthest) -> 0.0 ATR, sorted to the top group`);
    ok(/בתוך האזור/.test(await page.locator(`.row[data-t="${t}"] .r6`).textContent()), 'shows (בתוך האזור)');
    await page.reload(); await page.waitForSelector('.row');
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${OUT}/30_sort_zone_${name}.png` });
  console.log('     shot', `${OUT}/30_sort_zone_${name}.png`);
  await page.selectOption('#sort', 'default');
  await ctx.close();
}
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
