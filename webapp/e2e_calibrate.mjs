// Trend calibration page #/calibrate (Eyal 2026-10-26): 3 visible sections, bot view visible, 3y weekly chart, marks saved
// as label uptrend_mark, progress x/60, ticker opens the stock page; screenshots -> /workspace/calib_shots/.
// Usage: node e2e_calibrate.mjs [baseURL] [--live]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const SHOTS = '/workspace/calib_shots'; mkdirSync(SHOTS, { recursive: true });
const tag = process.argv.includes('--live') ? 'live' : 'local';
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
for (const [name, vp] of [['iphone', { width: 390, height: 844 }], ['desktop', { width: 1440, height: 900 }]]) {
  const page = await (await browser.newContext({ viewport: vp, locale: 'he-IL', deviceScaleFactor: name === 'iphone' ? 3 : 1 })).newPage();
  const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1'); await page.waitForSelector('.row');
  ok(await page.locator('#calLink').count() === 1, `${name}: list header link 'כיול מגמה'`);
  await page.click('#calLink'); await page.waitForSelector('.calcard');
  const secs = await page.locator('.calsec h2').allTextContents();
  ok(secs.length === 3 && /ברור שבמגמה עולה/.test(secs[0]) && /ברור שלא/.test(secs[1]) && /מתלבט/.test(secs[2]), `${name}: sections ${secs.join(' | ')}`);
  const n = await page.locator('.calcard').count(); ok(n === 60, `${name}: ${n} cards`);
  ok(await page.locator('.calbot').first().isVisible() && /דעת הבוט/.test(await page.locator('.calbot').first().textContent()), `${name}: bot view visible`);
  ok(await page.locator('text=הצג דעת הבוט').count() === 0, `${name}: no hide toggle`);
  await page.waitForSelector('canvas.calchart[data-drawn]');
  const box = await page.locator('canvas.calchart').first().boundingBox();
  ok(box && box.width / box.height > 2.2 && box.width / box.height < 2.6, `${name}: chart proportions ${box && (box.width / box.height).toFixed(2)} (${box && Math.round(box.width)}x${box && Math.round(box.height)})`);
  const mtg = page.locator('.calcard[data-cal="MTG"]');
  ok(await mtg.count() === 1 && (await mtg.evaluate((e) => e.closest('.calsec').dataset.group)) === 'unsure', `${name}: MTG in 'מתלבט'`);
  ok(/0\/60/.test(await page.locator('#calprog').textContent()), `${name}: progress 0/60`);
  const c1 = page.locator('.calcard').first();
  await c1.locator('.calnote').fill('בדיקה');
  await c1.locator('[data-mark="up"]').click(); await page.waitForTimeout(300);
  ok(/1\/60/.test(await page.locator('#calprog').textContent()) && await c1.locator('[data-mark="up"].on').count() === 1, `${name}: mark saved, progress 1/60`);
  const lab = await page.evaluate(() => window.__srs.S.labels.filter((l) => l.label === 'uptrend_mark'));
  ok(lab.length === 1 && lab[0].value === 'up' && lab[0].note === 'בדיקה' && /^\d{4}-\d\d-\d\d$/.test(lab[0].asof), `${name}: label ${JSON.stringify(lab[0])}`);
  await page.screenshot({ path: `${SHOTS}/${tag}_${name}_top.png` });
  await page.locator('.calsec[data-group="clear_not"]').scrollIntoViewIfNeeded(); await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/${tag}_${name}_clear_not.png` });
  await page.locator('.calsec[data-group="unsure"]').scrollIntoViewIfNeeded(); await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/${tag}_${name}_unsure.png` });
  const t = await c1.getAttribute('data-cal');
  await c1.locator('.caltk').click(); await page.waitForTimeout(800);
  ok(page.url().includes('#/t/' + t) && (await page.locator('#tk').textContent()) === t, `${name}: ticker opens stock page (${t})`);
  await page.goto(BASE + '?demo=1#/rules'); await page.waitForSelector('.rules h2, .rules section, .rules p');
  ok(await page.locator('.rules a[href="#/calibrate"]').count() >= 1, `${name}: rules page link`);
  ok(/מגמה נבדקת מחדש בכל שבוע/.test(await page.locator('.rules').textContent()), `${name}: rules: uptrend re-checked weekly`);
  ok(errors.length === 0, `${name}: no page errors ${errors.join(' | ')}`);
}
await browser.close();
