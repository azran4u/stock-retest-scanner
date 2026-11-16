// Confirmation candlestick patterns on the level (Eyal 2026-11-16, v2 after NTRA): card line, stock page section, chart marks (weekly +
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
  ok(JSON.stringify(got) === JSON.stringify(w), `${name}: entry signal -> ${w.length}: ${w.join(' ')}`);
  const wd = await page.evaluate(() => { const { S, factsOf, confOf } = window.__srs;
    return S.rows.filter((r) => !factsOf(r).unfit).filter((r) => (confOf(r.ticker, r)?.d || []).some((p) => p.entry)).map((r) => r.ticker); });
  ok(wd.length > 0 && wd.every((t) => got.includes(t)), `${name}: entry filter includes daily entries (${wd.length})`);
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
  const nEntry = (await want('!!c && c.entry')).length;
  const first = await page.$eval('.row', (e) => ({ conf: !!e.querySelector('.conf'), entry: !!e.querySelector('.conf.entry') }));
  ok(first.conf && (nEntry === 0 || first.entry), `${name}: sort 'תבנית אישור' puts ${nEntry ? 'an entry signal' : 'a pattern'} first`);
  await page.screenshot({ path: `${OUT}/${name}_list_confirm_sort.png` });
  // stock page VTWO: weekly three inside up on the level (week of 26/10, low 109.02 on 106.91-108.83), evidence only
  for (const [t, tf, key, other] of [['VTWO', 'W', 'W:inside3:2026-10-26', 'D:'], ['VSH', 'D', 'D:inside3:2026-11-09', 'W:']]) {
    const l = await page.evaluate((t) => window.__srs.confOf(t, window.__srs.S.byT.get(t)), t);
    ok(!!l && [...l.w, ...l.d].some((p) => `${p.tf}:${p.p}:${p.e}` === key), `${t}: ${key} on the level`);
    await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
    await page.locator(`[data-tf="${tf}"]`).click(); await page.waitForTimeout(700);
    const m = await page.evaluate(() => [...document.querySelectorAll('#chart g.confpat > g')].map((x) => x.dataset.conf));
    ok(m.includes(key) && !m.some((x) => x.startsWith(other)), `${name} ${t}: ${tf} chart marks ${m.join(' ')}`);
    await page.screenshot({ path: `${OUT}/${name}_${t}_${tf === 'W' ? 'weekly' : 'daily'}.png` });
    const items = await page.$$eval('#secConfirm li', (els) => els.map((e) => e.dataset.cp));
    ok(items.includes(key), `${name} ${t}: stock page lists ${items.join(' ')}`);
    await page.locator('[data-jump="secConfirm"]').click(); await page.waitForTimeout(600);
    if (mobile) ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name} ${t}: stock page has no horizontal overflow`);
    await page.screenshot({ path: `${OUT}/${name}_${t}_panel.png` });
    await page.locator('[data-tf="W"]').click(); await page.waitForTimeout(200);
  }
  // daily entry signals (v3): every one is a daily pattern on the level in the last 5 completed sessions, labelled (יומי)
  const de = await page.evaluate(() => { const { S, confOf, confDoc } = window.__srs; const out = [];
    for (const r of S.rows) { const l = confOf(r.ticker, r); for (const p of l?.d || []) if (p.entry) out.push([r.ticker, p.k, confDoc.consts.entry_days]); } return out; });
  ok(de.every(([, k, n]) => k < n), `${name}: daily entry signals within entry_days: ${de.map((x) => x[0]).join(' ')}`);
  if (de.length) {
    const t = de[0][0];
    await page.goto(BASE + `?demo=1#/t/${t}`); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(500);
    ok((await page.locator('#secConfirm').textContent()).includes('אות כניסה (יומי)'), `${name} ${t}: stock page labels the daily entry signal`);
    await page.locator('[data-tf="D"]').click(); await page.waitForTimeout(700);
    await page.screenshot({ path: `${OUT}/${name}_${t}_daily_entry.png` });
    await page.locator('[data-jump="secConfirm"]').click(); await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/${name}_${t}_daily_entry_panel.png` });
    await page.locator('[data-tf="W"]').click(); await page.waitForTimeout(200);
  }
  // NTRA (Eyal 2026-11-16): the v1 'tweezer' of 09/11 is gone
  const nt = await page.evaluate(() => window.__srs.confOf('NTRA', window.__srs.S.byT.get('NTRA')));
  ok(!nt || !nt.w.some((p) => p.p === 'tweezer'), `${name}: NTRA has no weekly tweezer on the level`);
  // GL (Eyal 2026-11-16, v4): the daily morning doji star of 09/11 formed in a sideways chop, no prior downtrend -> gone
  const gl = await page.evaluate(() => window.__srs.confOf('GL', window.__srs.S.byT.get('GL')));
  ok(!gl || !gl.d.some((p) => p.p === 'mdoji' && p.e === '2026-11-09'), `${name}: GL has no daily morning doji star of 09/11`);
  await ctx.close();
}
ok(!errors.length, 'no page errors ' + errors.slice(0, 3).join(' | '));
await browser.close();
