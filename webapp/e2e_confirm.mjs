// Confirmation candlestick patterns on the level (Eyal 2026-11-16): card line, stock page section, chart marks (weekly +
// daily), filters 'תבנית אישור על האזור ב-X' / 'אות כניסה', sort 'תבנית אישור'. iPhone 390 + laptop 1366 (mobile = desktop).
// Usage: node e2e_confirm.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/retest_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
for (const [name, vp, mobile] of [['iphone_390', { width: 390, height: 844 }, true], ['laptop_1366', { width: 1366, height: 768 }, false]]) {
  const ctx = await browser.newContext({ viewport: vp, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: mobile ? 2 : 1, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1#/'); await page.waitForSelector('.row');
  await page.evaluate(() => localStorage.removeItem('srs-app-v1')); await page.reload(); await page.waitForSelector('.row');
  await page.waitForFunction(() => window.__srs.confDoc != null && window.__srs.expertDoc != null); await page.waitForTimeout(400);
  const want = (fn) => page.evaluate((src) => { const { S, factsOf } = window.__srs; const f = new Function('c', 'return ' + src);
    return S.rows.filter((r) => !factsOf(r).unfit).filter((r) => f(factsOf(r).conf)).map((r) => r.ticker).sort(); }, fn);
  const shown = async () => (await page.$$eval('.row', (els) => els.map((e) => e.dataset.t))).sort();
  await page.locator('#ftog').click();
  const fe = page.locator('.fi[data-f="confirmEntry"]');
  ok((await fe.textContent()).includes('אות כניסה'), `${name}: entry filter listed`);
  await fe.locator('input[type=checkbox]').click(); await page.waitForTimeout(300);
  let w = await want('!!c && c.entry'), got = await shown();
  ok(w.length > 0 && JSON.stringify(got) === JSON.stringify(w), `${name}: entry signal -> ${w.length}: ${w.join(' ')}`);
  await fe.locator('input[type=checkbox]').click();
  const fc = page.locator('.fi[data-f="confirm"]');
  ok(await fc.locator('.fx').inputValue() === '2', `${name}: confirm filter default X=2`);
  await fc.locator('input[type=checkbox]').click(); await page.waitForTimeout(300);
  w = await want('!!c && (c.w.some((k) => k < 2) || c.d.some((k) => k < 10))'); got = await shown();
  ok(w.length > 0 && JSON.stringify(got) === JSON.stringify(w), `${name}: pattern within 2 weeks -> ${w.length}`);
  const lines = await page.$$eval('.row .conf', (els) => els.length);
  ok(lines === w.length, `${name}: every filtered card shows the pattern line (${lines})`);
  if (!mobile) await page.locator('#ftog').click(); else await page.locator('#fdone').click();
  await page.waitForTimeout(200);
  if (mobile) ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: list has no horizontal overflow`);
  await page.screenshot({ path: `${OUT}/${name}_list_confirm_filter.png` });
  await page.locator('#sort').selectOption('confirm'); await page.waitForTimeout(300);
  const firsts = await page.$$eval('.row', (els) => els.slice(0, 3).map((e) => e.querySelector('.conf')?.classList.contains('entry')));
  ok(firsts[0] === true, `${name}: sort 'תבנית אישור' puts an entry signal first`);
  await page.screenshot({ path: `${OUT}/${name}_list_confirm_sort.png` });
  // stock page DAR: weekly bullish engulfing on the level (week of 09/11) = entry signal; daily engulfing too
  const t = 'DAR';
  const l = await page.evaluate((t) => window.__srs.confOf(t, window.__srs.S.byT.get(t)), t);
  ok(!!l && l.entry && l.w.some((p) => p.p === 'engulf' && p.e === '2026-11-09'), `${t}: weekly engulfing 09/11 = entry signal`);
  await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
  await page.locator('[data-tf="W"]').click(); await page.waitForTimeout(600);
  const mw = await page.evaluate(() => [...document.querySelectorAll('#chart g.confpat > g')].map((x) => x.dataset.conf));
  ok(mw.includes('W:engulf:2026-11-09'), `${name} ${t}: weekly chart marks ${mw.join(' ')}`);
  await page.screenshot({ path: `${OUT}/${name}_${t}_weekly.png` });
  const items = await page.$$eval('#secConfirm li', (els) => els.map((e) => e.dataset.cp));
  ok(items.includes('W:engulf:2026-11-09') && items.includes('D:engulf:2026-11-09'), `${name} ${t}: stock page lists ${items.join(' ')}`);
  ok((await page.locator('#secConfirm h3').textContent()).includes('אות כניסה'), `${name} ${t}: section labelled entry signal`);
  await page.locator('[data-jump="secConfirm"]').click(); await page.waitForTimeout(600);
  if (mobile) ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: stock page has no horizontal overflow`);
  await page.screenshot({ path: `${OUT}/${name}_${t}_panel.png` });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.locator('[data-tf="D"]').click(); await page.waitForTimeout(700);
  const md = await page.evaluate(() => [...document.querySelectorAll('#chart g.confpat > g')].map((x) => x.dataset.conf));
  ok(md.includes('D:engulf:2026-11-09') && !md.some((x) => x.startsWith('W:')), `${name} ${t}: daily chart marks ${md.join(' ')}`);
  await page.screenshot({ path: `${OUT}/${name}_${t}_daily.png` });
  await page.locator('[data-tf="W"]').click(); await page.waitForTimeout(200);
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
