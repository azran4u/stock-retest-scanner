// Wide-screen master-detail + stock lists + Google sign-in button (Eyal 2026-10-30). Demo mode.
//  - laptop 1440 / iPad landscape 1180 / iPad portrait 820: list on the RIGHT, selected stock on the rest; row click
//    opens the stock in place (row highlighted), the per-row copy button (EXCHANGE:TICKER) is kept
//  - lists: built-in PASS / ★ / all; a static list (create, add tickers, rename, add from the stock page 📂, delete);
//    a saved search from the current filters; switching lists changes the side list; lists survive a reload
//  - mobile 390: unchanged flow (list page -> full stock page with back), lists available there too
//  - login: Google button only when the provider is on (?google=1 in demo), email code still there
// Usage: node e2e_split.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots/split_view';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const errors = [];
const idx = await (await fetch(BASE + 'data/index.json')).json();
const SYM = /^([A-Z]+:)?[A-Z0-9.]+$/;

async function open(name, vp, mobile, url = '?demo=1#/') {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(`${name}: ${e.message}`));
  await page.goto(BASE + url);
  return { ctx, page };
}
const rowsT = (page) => page.locator('#side .row').evaluateAll((els) => els.map((e) => e.dataset.t));

for (const [name, vp, mobile] of [['laptop', { width: 1440, height: 900 }, false], ['ipad_landscape', { width: 1180, height: 820 }, true], ['ipad_portrait', { width: 820, height: 1180 }, true]]) {
  const { ctx, page } = await open(name, vp, mobile);
  const click = (loc) => (mobile ? loc.tap() : loc.click());
  await page.waitForSelector('#side .row'); await page.waitForSelector('#main #chart canvas'); await page.waitForTimeout(1200);
  const sb = await page.locator('#side').boundingBox(), mb = await page.locator('#main').boundingBox();
  ok(sb && mb && sb.x > mb.x && Math.abs(sb.x + sb.width - vp.width) < 2, `${name}: list on the right (side x=${sb?.x}, w=${sb?.width}; main w=${mb?.width})`);
  ok(/#\/t\//.test(page.url()), `${name}: first stock opened automatically (${page.url().split('#')[1]})`);
  ok(await page.locator('#side .row.sel').count() === 1, `${name}: open stock highlighted in the list`);
  ok(await page.locator('#back').isHidden(), `${name}: no back button in split view`);
  const cps = await page.locator('#side .row .cpy').evaluateAll((els) => els.slice(0, 20).map((e) => e.dataset.copy));
  ok(cps.length > 0 && cps.every((c) => SYM.test(c)), `${name}: copy button per row (${cps.slice(0, 3).join(', ')})`);
  const ts = await rowsT(page);
  await click(page.locator(`#side .row[data-t="${ts[2]}"]`)); await page.waitForTimeout(900);
  ok(await page.locator('#tk').textContent() === ts[2] && await page.locator('#side').count() === 1, `${name}: row click shows ${ts[2]} next to the list`);
  ok(await page.locator('#side .row.sel').getAttribute('data-t') === ts[2], `${name}: selection follows`);
  await click(page.locator('#next')); await page.waitForTimeout(700);
  ok(await page.locator('#tk').textContent() === ts[3], `${name}: next (›) walks the side list (${ts[3]})`);
  for (const sel of ['#addZone', '#addLong', '#indbar', '#jump', '#panel #secCmd', '#star', '#niBtn', '#listsBtn', '#tkCopy'])
    ok(await page.locator(sel).count() === 1, `${name}: stock page has ${sel}`);
  await page.screenshot({ path: `${OUT}/${name}.png` });

  if (name === 'laptop') {
    const nAll = (await rowsT(page)).length;
    await page.selectOption('#listSel', 'pass'); await page.waitForTimeout(500);
    const pass = await rowsT(page);
    const allPass = await page.locator('#side .row').evaluateAll((els) => els.every((e) => !!e.querySelector('.badge.b-pass')));
    ok(pass.length > 0 && pass.length < nAll && allPass, `laptop: PASS list -> ${pass.length} rows, all PASS (all = ${nAll})`);
    ok(pass.includes(await page.locator('#tk').textContent()), 'laptop: open stock is in the PASS list');
    await page.selectOption('#listSel', 'all'); await page.waitForTimeout(300);
    const star = (await rowsT(page))[5];
    await page.locator(`#side .row[data-t="${star}"] .star`).click(); await page.waitForTimeout(300);
    await page.selectOption('#listSel', 'starred'); await page.waitForTimeout(400);
    ok(JSON.stringify(await rowsT(page)) === JSON.stringify([star]), `laptop: ★ list = [${star}]`);
    // static list from the manager
    await page.click('#listMgr'); await page.waitForSelector('#listSheet:not([hidden])');
    await page.fill('#lsNewName', 'מועמדים'); await page.click('#lsNewStatic'); await page.waitForTimeout(400);
    const lid = await page.evaluate(() => window.__srs.S.ui.list);
    const li = page.locator(`#listSheet .lsi[data-lid="${lid}"]`);
    const two = idx.rows.filter((r) => r.has_candles).slice(0, 2).map((r) => r.ticker);
    await li.locator('.lsadd').fill(`${two[0]}, nasdaq:${two[1].toLowerCase()} ZZZQ`); await li.locator('.lsaddb').click(); await page.waitForTimeout(400);
    ok(JSON.stringify(await page.evaluate((id) => window.__srs.S.lists.find((l) => l.id === id)?.tickers, lid)) === JSON.stringify([...two, 'ZZZQ']), `laptop: static list tickers ${two.join(',')},ZZZQ (prefix stripped)`);
    await page.locator(`#listSheet .lsi[data-lid="${lid}"] .lsname`).fill('מועמדים לכניסה');
    await page.locator(`#listSheet .lsi[data-lid="${lid}"] .lsname`).dispatchEvent('change'); await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/laptop_lists_sheet.png` });
    await page.click('#lsClose');
    ok((await page.locator('#listSel option:checked').textContent()).includes('מועמדים לכניסה'), 'laptop: renamed list selected in the switcher');
    { const got = await rowsT(page); ok(JSON.stringify([...got].sort()) === JSON.stringify([...two, 'ZZZQ'].sort()), `laptop: side list shows the static list, unknown ticker as a no-data row (${got})`); }
    // add the open stock from the stock page 📂
    await page.selectOption('#listSel', 'all'); await page.waitForTimeout(300);
    const other = (await rowsT(page)).find((t) => !two.includes(t));
    await page.locator(`#side .row[data-t="${other}"]`).click(); await page.waitForTimeout(600);
    await page.click('#listsBtn'); await page.locator(`#listsPop input[data-lid="${lid}"]`).check(); await page.waitForTimeout(400);
    ok((await page.evaluate((id) => window.__srs.S.lists.find((l) => l.id === id)?.tickers, lid)).includes(other) && await page.locator('#listsBtn.on').count() === 1, `laptop: 📂 adds ${other} to the static list`);
    await page.screenshot({ path: `${OUT}/laptop_add_to_list.png` });
    // saved search (dynamic) from the current filters
    await page.click('#ftog'); await page.locator('#fpanel .fi[data-f="st_pass"] input[type=checkbox]').check(); await page.waitForTimeout(300);
    await page.locator('#fpanel .fi[data-f="rr"] .fx').fill('3'); await page.waitForTimeout(300);
    const want = await rowsT(page);
    await page.click('#listMgr'); await page.fill('#lsNewName', 'PASS R:R≥3'); await page.click('#lsNewDyn'); await page.waitForTimeout(400);
    await page.click('#lsClose');
    const ui = await page.evaluate(() => window.__srs.S.ui);
    ok(Object.keys(ui.f).length === 0 && JSON.stringify(await rowsT(page)) === JSON.stringify(want) && want.length > 0, `laptop: saved search "PASS R:R≥3" -> ${want.length} rows, panel cleared`);
    // reload: lists come back (demo api is empty -> pushed from the local copy)
    await page.reload(); await page.waitForSelector('#side .row'); await page.waitForTimeout(800);
    const names = await page.locator('#listSel option').allTextContents();
    ok(names.some((n) => n.includes('מועמדים לכניסה')) && names.some((n) => n.includes('PASS R:R≥3')), `laptop: lists persisted (${names.join(' | ')})`);
    { const got = await rowsT(page); ok(JSON.stringify([...got].sort()) === JSON.stringify([...want].sort()), `laptop: active list remembered after reload (${got.length} vs ${want.length}: ${got.slice(0, 5)} / ${want.slice(0, 5)})`); }
    // delete
    await page.selectOption('#listSel', lid); await page.waitForTimeout(300);
    await page.click('#listMgr');
    page.once('dialog', (d) => d.accept());
    await page.locator(`#listSheet .lsi[data-lid="${lid}"] .lsdel`).click(); await page.waitForTimeout(400);
    await page.click('#lsClose');
    ok(!(await page.locator('#listSel option').allTextContents()).some((n) => n.includes('מועמדים')) && await page.evaluate(() => window.__srs.S.ui.list) === 'all', 'laptop: deleted list gone, back to all stocks');
    // resize across the breakpoint
    await page.setViewportSize({ width: 600, height: 900 }); await page.waitForTimeout(700);
    ok(await page.locator('#side').count() === 0 && await page.locator('#back').isVisible(), 'laptop: narrowed to 600px -> single stock page with back');
    await page.setViewportSize({ width: 1440, height: 900 }); await page.waitForTimeout(700);
    ok(await page.locator('#side').count() === 1 && await page.locator('#main #chart canvas').count() > 0, 'laptop: widened again -> split');
  }
  await ctx.close();
}

{ // mobile: unchanged flow
  const { ctx, page } = await open('mobile', { width: 390, height: 844 }, true);
  await page.waitForSelector('.list .row'); await page.waitForTimeout(800);
  ok(await page.locator('#side').count() === 0 && /#\/$/.test(page.url()), 'mobile: list page, no split, no auto-open');
  ok(await page.locator('#listSel').isVisible() && await page.locator('#listMgr').isVisible(), 'mobile: list switcher + manager');
  const cp = await page.locator('.list .row .cpy').first().getAttribute('data-copy');
  ok(SYM.test(cp), `mobile: copy button kept (${cp})`);
  await page.screenshot({ path: `${OUT}/mobile_list.png` });
  await page.selectOption('#listSel', 'pass'); await page.waitForTimeout(400);
  const n = await page.locator('.list .row').count();
  ok(n > 0 && await page.locator('.list .row').evaluateAll((els) => els.every((e) => !!e.querySelector('.badge.b-pass'))), `mobile: PASS list ${n} rows`);
  const t = await page.locator('.list .row').first().getAttribute('data-t');
  await page.locator('.list .row').first().tap(); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(900);
  ok(await page.locator('#tk').textContent() === t && await page.locator('#back').isVisible() && await page.locator('.list').count() === 0, `mobile: tap opens ${t} full screen with back`);
  ok(await page.locator('#listsBtn').isVisible(), 'mobile: 📂 add-to-list on the stock page');
  await page.locator('#listsBtn').tap(); await page.fill('#lpNew', 'נייד'); await page.locator('#lpNewB').tap(); await page.waitForTimeout(400);
  ok(await page.evaluate((x) => window.__srs.S.lists.some((l) => l.name === 'נייד' && l.tickers.includes(x)), t), `mobile: new list with ${t} from the stock page`);
  await page.screenshot({ path: `${OUT}/mobile_stock.png` });
  await page.locator('#back').tap(); await page.waitForSelector('.list .row');
  ok(await page.locator('#side').count() === 0, 'mobile: back to the list');
  await ctx.close();
}

{ // login
  const { ctx, page } = await open('login', { width: 390, height: 844 }, true, '?demo=login&google=1#/');
  await page.waitForSelector('#google:not([hidden])');
  ok(await page.locator('#send').isVisible(), 'login: Google button + email code fallback');
  await page.screenshot({ path: `${OUT}/login_google.png` });
  await page.locator('#google').tap(); await page.waitForSelector('.list .row');
  ok(true, 'login: Google sign-in (demo) opens the app');
  await ctx.close();
  const b = await open('login2', { width: 390, height: 844 }, true, '?demo=login#/');
  await b.page.waitForSelector('#send'); await b.page.waitForTimeout(500);
  ok(await b.page.locator('#google').isHidden(), 'login: no Google button while the provider is off');
  await b.ctx.close();
  const c = await open('login3', { width: 390, height: 844 }, true, '?demo=login#error=server_error&error_description=Database+error+saving+new+user');
  await c.page.waitForSelector('#send');
  ok((await c.page.locator('#authErr').textContent()).includes('לא מורשה'), 'login: a rejected account sees "not allowed"');
  await c.ctx.close();
}

ok(errors.length === 0, `no page errors${errors.length ? ': ' + errors.join(' | ') : ''}`);
await browser.close();
