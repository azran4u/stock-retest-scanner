// Independent list filters (logical AND) + rules page (Eyal 2026-10-26). Demo mode, iPhone 390 + desktop 1440.
// Usage: node e2e_filters.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4181/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/filters_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['desktop_1440', { width: 1440, height: 900 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.goto(BASE + '?demo=1#/');
  await page.waitForSelector('.row');
  await page.evaluate(() => { localStorage.removeItem('srs-app-v1'); });
  await page.reload(); await page.waitForSelector('.row');
  const count = () => page.locator('.row').count();
  const shown = () => page.evaluate(() => +document.querySelector('.sortrow .small').textContent.match(/\d+/)[0]);
  const facts = () => page.evaluate(() => window.__srs.S.rows.filter((r) => !window.__srs.factsOf(r).unfit).map((r) => ({ t: r.ticker, ...window.__srs.factsOf(r) })));
  const all = await count();
  ok(await page.locator('.chip[data-chip]').count() === 0, `${name}: old single-select chip row is gone`);
  ok(all > 10 && all === await shown(), `${name}: ${all} rows, match count shown`);
  const tog = page.locator('#ftog');
  ok(/סינון/.test(await tog.textContent()) && await page.locator('#fpanel').isHidden(), `${name}: collapsed filter button`);
  await tog.click();
  ok(await page.locator('#fpanel').isVisible() && await page.locator('#fpanel .fi').count() >= 25, `${name}: panel open with ${await page.locator('#fpanel .fi').count()} filters`);
  const F = await facts();
  const on = async (id) => { await page.locator(`.fi[data-f="${id}"] input[type=checkbox]`).click(); await page.waitForTimeout(150); };
  const setX = async (id, v) => { await page.locator(`.fi[data-f="${id}"] .fx`).fill(String(v)); await page.waitForTimeout(150); };
  // R:R ≥ 2
  await on('rr');
  let want = F.filter((f) => f.rr != null && f.rr >= 2).length;
  ok(await count() === want && /1/.test(await page.locator('.fcount').textContent()), `${name}: R:R ≥ 2 -> ${want} rows, count badge 1`);
  await setX('rr', 4);
  want = F.filter((f) => f.rr != null && f.rr >= 4).length;
  ok(await count() === want, `${name}: R:R ≥ 4 param -> ${want}`);
  await setX('rr', 2);
  const w2 = F.filter((f) => f.rr != null && f.rr >= 2).length;
  // AND uptrend
  await on('uptrend');
  const wantAnd = F.filter((f) => f.rr != null && f.rr >= 2 && f.technical === true).length;
  ok(await count() === wantAnd && wantAnd < w2, `${name}: R:R ≥ 2 AND uptrend -> ${wantAnd} (< ${w2})`);
  // AND earnings ≥ 14
  await on('earn');
  const wantAnd3 = F.filter((f) => f.rr != null && f.rr >= 2 && f.technical === true && f.daysToEarn != null && f.daysToEarn >= 14).length;
  ok(await count() === wantAnd3 && wantAnd3 <= wantAnd && /3/.test(await page.locator('.fcount').textContent()), `${name}: + days to earnings ≥ 14 -> ${wantAnd3} (3 active)`);
  await page.screenshot({ path: `${OUT}/filters_panel_${name}.png` });
  // persistence
  await page.reload(); await page.waitForSelector('.row');
  ok(await count() === wantAnd3 && await page.locator('#fpanel').isVisible() && await page.locator('.fi[data-f="rr"] .fx').inputValue() === '2', `${name}: filters persisted after reload`);
  // clear all
  await page.locator('#fclear').click(); await page.waitForTimeout(150);
  ok(await count() === all && await page.locator('#fclear').isHidden(), `${name}: clear all -> ${all}`);
  // weekly reversal kinds + X weeks
  await on('revW');
  const wk = (f, kinds, x) => { const from = new Date(f.today + 'T00:00:00Z'); from.setUTCDate(from.getUTCDate() - 7 * x); const s = from.toISOString().slice(0, 10); return kinds.some((k) => f.revW[k] && f.revW[k] >= s); };
  want = F.filter((f) => wk(f, ['hammer', 'engulfing'], 2)).length;
  ok(await count() === want, `${name}: weekly reversal (hammer/engulfing) ≤ 2 weeks -> ${want}`);
  await page.locator('.fi[data-f="revW"] .kd[data-k="strong_close"]').click(); await page.waitForTimeout(150);
  want = F.filter((f) => wk(f, ['hammer', 'engulfing', 'strong_close'], 2)).length;
  ok(await count() === want, `${name}: + strong close kind -> ${want}`);
  await setX('revW', 8);
  want = F.filter((f) => wk(f, ['hammer', 'engulfing', 'strong_close'], 8)).length;
  ok(await count() === want, `${name}: 8 weeks -> ${want}`);
  await page.locator('#fclear').click(); await page.waitForTimeout(150);
  // unfit tri-state
  await page.evaluate(async () => { const s = window.__srs.S; s.labels.push({ ticker: s.rows[0].ticker, label: 'not_interesting', value: 'yes', note: 'unfit', asof: '2026-10-26', until: '2099-01-01', created_at: new Date().toISOString() }); });
  await page.locator('.fi[data-f="rr"] input[type=checkbox]').click(); await page.locator('.fi[data-f="rr"] input[type=checkbox]').click(); await page.waitForTimeout(150);
  ok(await count() === all - 1, `${name}: unfit hidden by default`);
  await page.locator('.fi[data-f="unfit"] .seg[data-mode="only"]').click(); await page.waitForTimeout(150);
  ok(await count() === 1, `${name}: unfit only -> 1`);
  await page.locator('.fi[data-f="unfit"] .seg[data-mode="all"]').click(); await page.waitForTimeout(150);
  ok(await count() === all, `${name}: unfit show too -> ${all}`);
  await page.evaluate(() => { const s = window.__srs.S; s.labels = s.labels.filter((l) => l.until !== '2099-01-01'); });
  await page.locator('#fclear').click(); await page.waitForTimeout(150);
  // sector select
  const sec = F.find((f) => f.sector)?.sector;
  if (sec) { await page.locator('.fi[data-f="sector"] .fsel').selectOption(sec); await page.waitForTimeout(150);
    ok(await count() === F.filter((f) => f.sector === sec).length, `${name}: sector ${sec}`); }
  // search still works with filters
  await page.fill('#q', F[0].t); await page.waitForTimeout(200);
  ok(await count() <= 1, `${name}: search + filters`);
  await page.fill('#q', ''); await page.locator('#fclear').click();
  // rules page
  await page.locator('#rulesLink').click();
  await page.waitForSelector('.rsec');
  const txt = await page.locator('.rules').textContent();
  ok(/מחיר מעל \$10/.test(txt) && /SMA50/.test(txt) && !/מחיר מעל הממוצע הנע 200/.test(txt), `${name}: rules: FinViz = price > $10 + below SMA50, no SMA200 condition`);
  ok(/PASS/.test(txt) && /\$50M/.test(txt) && /R:R ≥ 2/.test(txt) && /מידע בלבד/.test(txt) && /פטיש הפוך/.test(txt) && /לא מתאימה לשיטה/.test(txt) && /גודל פוזיציה/.test(txt), `${name}: rules: PASS / info warnings / unfit / sizing sections`);
  ok(await page.locator('.rsec').count() >= 9 && await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: ${await page.locator('.rsec').count()} sections, no horizontal overflow`);
  await page.screenshot({ path: `${OUT}/rules_${name}.png`, fullPage: true });
  await page.screenshot({ path: `${OUT}/rules_top_${name}.png` });
  await page.locator('#back').click(); await page.waitForSelector('.row');
  ok(await count() === all, `${name}: back to list`);
  console.log('     shots', `${OUT}/filters_panel_${name}.png`, `${OUT}/rules_${name}.png`);
  await ctx.close();
}
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
