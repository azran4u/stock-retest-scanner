// Mobile parity (Eyal 2026-10-27: "on mobile I don't see SNX's overview and can't send a message to the bot; the mobile
// version should have the same capabilities as desktop"). Demo mode (nothing leaves the browser) at 390x844 with an
// open position (positions bar) and an SNX overview: every page fits the width, the stock page scrolls as one page and
// its overview / bot box / Fib / unfit / note are reachable via the jump chips, the bot message is sent (demo) from the
// stock page and from the general 💬 sheet, filters open as a bottom sheet. Usage: node e2e_mobile.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/mobile_shots';
mkdirSync(OUT, { recursive: true });
const RES = JSON.parse(readFileSync(new URL('./e2e_research.fixture.json', import.meta.url)));
RES.push({ ...RES[0], ticker: 'SNX', summary_he: 'תחום: הפצת טכנולוגיה (TD SYNNEX), שירותי IT ושרשרת אספקה.\nדוח אחרון: דמו לבדיקה בלבד.\nאנליסטים: דמו.\nחדשות: דמו.' });
const POS = [{ ticker: 'SWK', qty: 1, entry_price: 88.68, stop: 82.27, target: 102.48, entry_date: '2026-10-01', status: 'open' }];
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
await ctx.addInitScript(([r, p]) => { window.__demoResearch = r; window.__demoPositions = p; localStorage.removeItem('srs_posbar_collapsed'); }, [RES, POS]);
const page = await ctx.newPage();
const errors = []; page.on('pageerror', (e) => errors.push(e.message));
const noHScroll = async (n) => ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${n}: no horizontal overflow`);
const visibleInViewport = (sel) => page.evaluate((s) => { const r = document.querySelector(s)?.getBoundingClientRect(); return !!r && r.top >= 0 && r.top < window.innerHeight && r.height > 0; }, sel);

// list + filters sheet + general bot sheet
await page.goto(BASE + '?demo=1'); await page.waitForSelector('.list .row'); await page.waitForTimeout(800);
await noHScroll('list');
ok(await page.locator('#botFab').isVisible(), 'list: 💬 bot button visible');
await page.screenshot({ path: `${OUT}/01_list.png` });
await page.tap('#ftog'); await page.waitForTimeout(250);
const sheet = await page.evaluate(() => { const r = document.querySelector('#fpanel').getBoundingClientRect(); return { b: Math.round(r.bottom), h: Math.round(r.height), pos: getComputedStyle(document.querySelector('#fpanel')).position }; });
ok(sheet.pos === 'fixed' && sheet.b <= 844 && sheet.h > 300, `filters: bottom sheet (${JSON.stringify(sheet)})`);
ok(await page.locator('#fdone').isVisible() && await page.locator('#fpanel .fi').count() >= 25, 'filters: all filters + "show N" button');
await page.locator('.fi[data-f="rr"] .ft').first().tap(); await page.waitForTimeout(150);
await page.screenshot({ path: `${OUT}/02_filters_sheet.png` });
await page.tap('#fdone'); await page.waitForTimeout(150);
ok(await page.locator('#fpanel').isHidden(), 'filters: sheet closes with "show N"');
await page.locator('#fclear').tap();
await page.tap('#botFab'); await page.waitForSelector('#botSheet:not([hidden])');
await page.fill('#gcmd', 'בדיקת מובייל (דמו, לא נשלח)');
await page.screenshot({ path: `${OUT}/03_bot_general_sheet.png` });
await page.tap('#gsend'); await page.waitForTimeout(300);
const g = await page.evaluate(() => window.__demoApi.commands[0]);
ok(g && g.ticker === null && /בדיקת מובייל/.test(g.text), 'general bot message sent (demo store, ticker null)');
ok(await page.locator('#gcmds li', { hasText: 'בדיקת מובייל' }).count() === 1, 'general message listed with status');
await page.tap('#botClose');

// SNX stock page
await page.goto(BASE + '?demo=1#/t/SNX'); await page.waitForSelector('#research'); await page.waitForTimeout(1500);
await noHScroll('SNX');
await page.screenshot({ path: `${OUT}/04_snx_top.png` });
ok(await page.locator('[data-jump="research"]').isVisible(), 'SNX: jump chip to the overview');
ok(await page.evaluate(() => document.scrollingElement.scrollHeight > window.innerHeight + 300), 'SNX: page scrolls as one page');
await page.tap('[data-jump="research"]'); await page.waitForTimeout(700);
ok(await visibleInViewport('#research') && await page.evaluate(() => document.querySelector('#research').open), 'SNX: overview on screen and open after the jump');
ok(await page.locator('#chhead').isVisible() && (await page.evaluate(() => document.querySelector('#chhead').getBoundingClientRect().top)) >= 0, 'SNX: header stays on top (sticky)');
await page.screenshot({ path: `${OUT}/05_snx_overview.png` });
await page.tap('[data-jump="secCmd"]').catch(async () => { await page.evaluate(() => window.scrollTo(0, 0)); await page.tap('[data-jump="secCmd"]'); });
await page.waitForTimeout(700);
ok(await visibleInViewport('#secCmd'), 'SNX: bot box on screen after the jump');
await page.fill('#cmd', 'בדיקת מובייל ל-SNX (דמו, לא נשלח)');
await page.screenshot({ path: `${OUT}/06_snx_bot_box.png` });
await page.tap('#sendCmd'); await page.waitForTimeout(300);
const c = await page.evaluate(() => window.__demoApi.commands[0]);
ok(c && c.ticker === 'SNX' && /SNX/.test(c.text), 'SNX: per-stock bot message sent (demo store)');
ok(await page.locator('#secCmd .cmds li', { hasText: 'בדיקת מובייל' }).count() === 1, 'SNX: message listed under the box');
// 💬 on the stock page jumps to the stock's box
await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(200);
await page.tap('#botFab'); await page.waitForTimeout(700);
ok(await visibleInViewport('#secCmd') && await page.locator('#botSheet').isHidden(), 'SNX: 💬 jumps to the stock bot box');
// Fib + unfit + star + drawings
await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(200);
await page.tap('[data-fib]'); await page.waitForTimeout(300);
ok(await page.locator('#secFib').count() === 1, 'SNX: Fib panel');
await page.tap('#niBtn'); await page.waitForTimeout(200);
ok(await page.locator('#unfitPop').isVisible(), 'SNX: unfit pop opens');
await page.screenshot({ path: `${OUT}/07_snx_fib_unfit.png` });
await page.tap('#unfitClose');
await page.tap('#star'); await page.waitForTimeout(200);
ok((await page.textContent('#star')) === '★', 'SNX: star toggles');
await page.tap('#star');
await page.tap('[data-jump="secUnfit"]'); await page.waitForTimeout(500);
ok(await visibleInViewport('#secUnfit'), 'SNX: unfit section reachable');
await page.tap('[data-jump="secNote"]').catch(() => {}); await page.waitForTimeout(500);
// rules + calibrate
for (const [n, h, sel] of [['rules', '#/rules', '.rsec'], ['calibrate', '#/calibrate', '.calcard']]) {
  await page.goto(BASE + '?demo=1' + h); await page.waitForSelector(sel, { timeout: 15000 }); await page.waitForTimeout(800);
  await noHScroll(n);
  await page.screenshot({ path: `${OUT}/08_${n}.png` });
}
// login (logged out)
await page.goto(BASE + '?demo=login'); await page.waitForSelector('#google'); await noHScroll('login');
ok(await page.locator('#botFab').isHidden(), 'login: no 💬 when logged out');
await page.screenshot({ path: `${OUT}/09_login.png` });
ok(errors.length === 0, `no page errors ${errors.join(' | ')}`);
await browser.close();
