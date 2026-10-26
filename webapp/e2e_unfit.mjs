// 'לא מתאימה לשיטה' (Eyal 2026-10-24: merges 'לא מעניינת' + 'לא טכנית'): one button, duration picks (default 8 weeks) +
// custom date + optional reason, stored as label not_interesting (until, note 'unfit...'), remaining time + return now,
// list hide / chip, automatic return after expiry. Also checks the stock page has no zone / Long level inputs any more.
// Demo mode. Usage: node e2e_unfit.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/stock_page_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const T = 'CSCO';
const todayIL = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Jerusalem' });
const add = (n) => { const d = new Date(todayIL() + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const dm = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const browser = await chromium.launch();
const errors = [];
const lab = (page) => page.evaluate((t) => { const ls = window.__srs.S.labels.filter((l) => l.ticker === t && l.label === 'not_interesting'); return ls[ls.length - 1] || null; }, T);
for (const [name, vp, mobile] of [['desktop_1440', { width: 1440, height: 900 }, false], ['iphone_390', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  await page.goto(BASE + '?demo=1#/t/' + T);
  await page.waitForSelector('#chart canvas'); await page.waitForTimeout(700);
  // zone / Long section removed: compact read-only lines, no inputs; status line with R:R + sizing kept
  ok(await page.locator('#panel input[data-f]').count() === 0 && await page.locator('.card.dline').count() >= 1, `${name}: no zone / Long level inputs; ${await page.locator('.card.dline').count()} compact drawing lines`);
  const sl = (await page.locator('#statusLine').textContent()).replace(/\s+/g, ' ').trim();
  ok(/PASS|FAIL/.test(sl) && /R:R/.test(sl), `${name}: status line kept: "${sl}"`);
  ok(await page.locator('.card.dline .act[data-act="delete"]').count() >= 1, `${name}: delete still reachable (🗑 on the line)`);
  await page.screenshot({ path: `${OUT}/70_stock_page_${name}.png` }); console.log('     shot', `${OUT}/70_stock_page_${name}.png`);
  await page.locator('#panel').evaluate((p) => p.scrollIntoView()); await page.evaluate(() => { const p = document.querySelector('#panel'); p.scrollTop = 0; });
  ok(await page.locator('.lab[data-v]').count() === 0 && await page.locator('#niWeeks').count() === 0, `${name}: old 'טכנית? כן/לא' + 'לא מעניינת' controls gone`);
  // panel defaults
  const sec = page.locator('.unfitsec');
  ok(await sec.locator('.wkb').count() === 4 && (await sec.locator('.wkb.on').textContent()).includes('8') && (await sec.locator('#unfitWhen').textContent()).includes(dm(add(56))),
    `${name}: picks 4/8/12/26 weeks, default 8 -> returns ${dm(add(56))}`);
  // header button -> popover, pick 4 weeks + reason
  await page.click('#niBtn'); await page.waitForSelector('#unfitPop:not([hidden])');
  const pop = page.locator('#unfitPop');
  await pop.locator('.wkb[data-w="4"]').click();
  ok((await pop.locator('#unfitWhen').textContent()).includes(dm(add(28))), `${name}: 4 weeks -> returns ${dm(add(28))}`);
  await pop.locator('#unfitWhy').fill('טווח צדדי');
  await pop.locator('#niOn').click(); await page.waitForTimeout(300);
  let l = await lab(page);
  ok(l && l.value === 'yes' && l.until === add(28) && l.note === 'unfit: טווח צדדי', `${name}: saved label not_interesting yes until ${l?.until}, note "${l?.note}"`);
  ok(await page.locator('#unfitPop').isHidden() && /לא מתאימה לשיטה/.test(await page.locator('#tkb').textContent()) && await page.locator('#niBtn.on').count() === 1, `${name}: popover closed, header badge + button on`);
  const stt = (await page.locator('.unfitsec #unfitState').textContent()).replace(/\s+/g, ' ');
  ok(stt.includes(`חוזרת ב-${dm(add(28))}`) && stt.includes('עוד 28 ימים'), `${name}: remaining time "${stt}"`);
  await page.locator('.unfitsec').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${OUT}/71_unfit_marked_${name}.png` }); console.log('     shot', `${OUT}/71_unfit_marked_${name}.png`);
  // list: hidden from 'הכל', shown under the chip with the return date
  await page.click('#back'); await page.waitForSelector('.row');
  await page.evaluate(() => window.__srs.setChip('all')); await page.waitForTimeout(200);
  ok(await page.locator(`.row[data-t="${T}"]`).count() === 0, `${name}: hidden from the list`);
  await page.evaluate(() => window.__srs.setChip('ni')); await page.waitForTimeout(200);
  const rt = await page.locator(`.row[data-t="${T}"]`).textContent();
  ok(rt.includes('לא מתאימה לשיטה') && rt.includes(`חוזרת ב-${dm(add(28))}`), `${name}: under 'לא מתאימות לשיטה' with the return date`);
  await page.evaluate(() => window.__srs.setChip('all'));
  // return now
  await page.goto(BASE + '?demo=1#/t/' + T); await page.waitForSelector('#chart canvas'); await page.waitForTimeout(400);
  await page.locator('.unfitsec #niOff').click(); await page.waitForTimeout(300);
  l = await lab(page);
  ok(l.value === 'no' && await page.locator('#niBtn.on').count() === 0 && await page.locator('.unfitsec .wkb').count() === 4, `${name}: 'החזר עכשיו' -> value no, picks shown again`);
  await page.locator('.unfitsec #unfitDate').fill(add(10)); await page.locator('.unfitsec #unfitDate').dispatchEvent('change');
  ok((await page.locator('.unfitsec #unfitWhen').textContent()).includes(dm(add(10))), `${name}: custom date -> returns ${dm(add(10))}`);
  await page.locator('.unfitsec #niOn').click(); await page.waitForTimeout(300);
  l = await lab(page);
  ok(l.value === 'yes' && l.until === add(10) && l.note === 'unfit', `${name}: custom date saved until ${l.until}, note "${l.note}" (no reason)`);
  await page.locator('.unfitsec #niOff').click(); await page.waitForTimeout(300);
  ok((await lab(page)).value === 'no', `${name}: returned again`);
  // expiry: a mark that ended yesterday -> back automatically
  await page.evaluate(({ t, y }) => { const S = window.__srs.S; S.labels.push({ ticker: t, label: 'not_interesting', value: 'yes', note: 'unfit', asof: '2026-01-01', until: y, created_at: '2026-01-01T00:00:00Z' }); }, { t: T, y: add(-1) });
  ok(!(await page.evaluate((t) => window.__srs.badgesOf(window.__srs.S.byT.get(t)).includes('ni'), T)), `${name}: expired mark (until ${add(-1)}) -> back automatically`);
  await ctx.close();
}
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
