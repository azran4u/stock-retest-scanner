// Expert zone overlay (Eyal 2026-11-01): app/data/expert_zones.json -> dashed purple box 'אזור מומחים <score>' on the
// weekly AND daily chart, toggle chip, score + factor breakdown on the stock page, small badge in the list. It must NOT
// touch drawings (none inserted / updated) and must NOT change PASS (statuses identical with the file blocked).
// Demo mode, iPhone 390 + laptop 1366. Usage: node e2e_expert_zone.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/expert_zone';
mkdirSync(OUT, { recursive: true });
const doc = JSON.parse(readFileSync(new URL('../app/data/expert_zones.json', import.meta.url)));
const okT = Object.keys(doc.tickers).filter((t) => doc.tickers[t].ok);
const noT = Object.keys(doc.tickers).filter((t) => !doc.tickers[t].ok);
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const SHOT_T = process.env.SHOT_T || 'KBWB';
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  // statuses with the expert file blocked = baseline
  const p0 = await ctx.newPage();
  await p0.route('**/expert_zones.json', (r) => r.abort());
  await p0.goto(BASE + '?demo=1#/'); await p0.waitForSelector('.row');
  await p0.evaluate(() => localStorage.removeItem('srs-app-v1')); await p0.reload(); await p0.waitForSelector('.row');
  const base = await p0.evaluate(() => window.__srs.S.rows.map((r) => [r.ticker, window.__srs.liveOf(r)?.status ?? r.status]));
  ok(await p0.locator('.b-expert').count() === 0, `${name}: no expert badge without the file`);
  await p0.close();

  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.waitForFunction(() => window.__srs.expertDoc != null);
  await page.waitForTimeout(300);
  const st = await page.evaluate(() => window.__srs.S.rows.map((r) => [r.ticker, window.__srs.liveOf(r)?.status ?? r.status]));
  ok(JSON.stringify(st) === JSON.stringify(base), `${name}: PASS / statuses identical with and without expert zones (${st.length} rows)`);
  // list badges: one per expert ticker that is in the list
  const inList = await page.evaluate((ts) => ts.filter((t) => window.__srs.S.byT.has(t)), Object.keys(doc.tickers));
  await page.locator('#q, input[type=search]').first().fill(SHOT_T).catch(() => {});
  await page.waitForTimeout(300);
  const badge = page.locator(`.row[data-t="${SHOT_T}"] .b-expert`);
  ok(await badge.count() === 1 && (await badge.textContent()).includes(String(doc.tickers[SHOT_T].score)), `${name}: list badge 'מומחים ${doc.tickers[SHOT_T].score}' on ${SHOT_T} (${inList.length} expert tickers in the list)`);
  await page.screenshot({ path: `${OUT}/${name}_list_badge.png` });

  const drawBefore = await page.evaluate(() => JSON.stringify(window.__demoApi.drawings));
  for (const t of [SHOT_T, okT.find((x) => x !== SHOT_T)]) {
    const e = doc.tickers[t];
    await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#chart canvas');
    await page.waitForFunction(() => window.__srs.expertDoc != null);
    // weekly
    await page.locator('[data-tf="W"]').click();
    await page.waitForSelector('#chart g.expert', { timeout: 5000 }).catch(() => {});
    const geo = await page.evaluate(({ top, bottom }) => {
      const cv = window.__srs.cv, r = document.querySelector('#chart g.expert rect');
      if (!r) return null;
      const yt = cv.candles.priceToCoordinate(top), yb = cv.candles.priceToCoordinate(bottom);
      return { y: +r.getAttribute('y'), h: +r.getAttribute('height'), yt, yb, dash: r.getAttribute('stroke-dasharray'), label: document.querySelector('#chart g.expert text').textContent };
    }, e);
    ok(geo && Math.abs(geo.y - Math.min(geo.yt, geo.yb)) < 1.5 && Math.abs(geo.h - Math.abs(geo.yb - geo.yt)) < 2 && geo.dash, `${name} ${t}: weekly dashed box at ${e.bottom}-${e.top}`);
    ok(geo && geo.label === `אזור מומחים ${e.score}`, `${name} ${t}: label '${geo?.label}'`);
    const sec = page.locator('#secExpert');
    ok(await sec.count() === 1 && (await sec.textContent()).includes(`ציון ${e.score}/100`), `${name} ${t}: stock page score ${e.score}/100`);
    ok(await sec.locator('tbody tr').count() === e.factors.length && e.factors.length === 9, `${name} ${t}: 9 factor rows with sources`);
    ok((await sec.textContent()).includes('לא משנה את האזור הנוכחי'), `${name} ${t}: 'separate, read-only' note`);
    if (t === SHOT_T) {
      await page.screenshot({ path: `${OUT}/${name}_${t}_weekly.png` });
      await sec.scrollIntoViewIfNeeded(); await page.waitForTimeout(200);
      await page.screenshot({ path: `${OUT}/${name}_${t}_score.png` });
      await page.evaluate(() => window.scrollTo(0, 0));
    }
    // daily
    await page.locator('[data-tf="D"]').click(); await page.waitForTimeout(400);
    ok(await page.locator('#chart g.expert').count() === 1, `${name} ${t}: shown on the daily chart too`);
    if (t === SHOT_T) await page.screenshot({ path: `${OUT}/${name}_${t}_daily.png` });
    // toggle off / on
    await page.locator('[data-expert]').click(); await page.waitForTimeout(250);
    ok(await page.locator('#chart g.expert').count() === 0, `${name} ${t}: toggle hides it`);
    await page.locator('[data-expert]').click(); await page.waitForTimeout(250);
    ok(await page.locator('#chart g.expert').count() === 1, `${name} ${t}: toggle shows it again`);
    await page.locator('[data-tf="W"]').click(); await page.waitForTimeout(200);
  }
  if (noT.length) {
    const t = noT[0];
    await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(400);
    ok(await page.locator('#chart g.expert').count() === 0 && (await page.locator('#secExpert').textContent()).includes('אין רמת מומחים'), `${name} ${t}: 'no expert level' shown, no box`);
  }
  const drawAfter = await page.evaluate(() => JSON.stringify(window.__demoApi.drawings));
  ok(drawAfter === drawBefore, `${name}: drawings untouched`);
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
