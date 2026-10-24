// Headless iPhone-15-Pro-sized smoke test in demo mode (in-memory backend). Usage: node e2e.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_screens';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'he-IL' });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

await page.goto(BASE + '?demo=login');
await page.waitForSelector('#send');
await page.screenshot({ path: `${OUT}/01_login.png` });
await page.click('#send'); await page.waitForSelector('#codebox:not([hidden])');
await page.fill('#code', '123456'); await page.click('#verify');
await page.waitForSelector('.row');
ok(true, 'login (demo) -> list');

await page.goto(BASE + '?demo=1');
await page.waitForSelector('.row');
const n = await page.locator('.row').count();
ok(n > 50, `list rows ${n}`);
await page.screenshot({ path: `${OUT}/02_list.png` });
await page.click('.chip[data-chip="pass"]');
const np = await page.locator('.row').count();
ok(np > 0 && np < n, `PASS filter ${np}`);
await page.fill('#q', 'CSC'); await page.waitForTimeout(100);
ok((await page.locator('.row').count()) >= 1, 'search CSC');
await page.screenshot({ path: `${OUT}/03_list_filtered.png` });

page.on('dialog', (d) => d.accept());
await page.locator('.row[data-t="CSCO"]').tap();
await page.waitForSelector('#chart canvas');
await page.waitForTimeout(600);
const box = await page.locator('#chart').boundingBox();
const X = box.x + box.width * 0.55;
// TradingView drawings arrive as normal editable rows (source tv)
const tvCards = page.locator('.card[data-id]');
ok((await tvCards.count()) === 2 && (await page.locator('.card .b-tv').count()) === 2, 'TV zone + long shown as compact drawing lines');
await page.locator('.card[data-id]').first().locator('.selbtn').tap();
await page.waitForSelector('g.h[data-key="zone_top"]');
const zh = await page.locator('g.h[data-key="zone_top"] circle').nth(1).boundingBox();
const z0 = await page.evaluate(() => [...window.__srs.S.drawings.values()].find((d) => d.ticker === 'CSCO' && d.source === 'tv' && d.kind === 'zone').zone_top);
await page.mouse.move(zh.x + zh.width / 2, zh.y + zh.height / 2); await page.mouse.down();
await page.mouse.move(zh.x + zh.width / 2, zh.y - 25, { steps: 5 }); await page.mouse.up(); await page.waitForTimeout(200);
const z1 = await page.evaluate(() => [...window.__srs.S.drawings.values()].find((d) => d.ticker === 'CSCO' && d.source === 'tv' && d.kind === 'zone').zone_top);
ok(z1 > z0, `drag TV zone top ${z0} -> ${z1}`);
await page.locator('.card[data-id]').nth(1).locator('.selbtn').tap(); await page.waitForTimeout(2800);
await page.screenshot({ path: `${OUT}/09_tv_drawing_editable.png` });
// delete both TV drawings (soft delete)
for (let i = 0; i < 2; i++) { await page.locator('.card[data-id] .act[data-act="delete"]').first().tap(); await page.waitForTimeout(150); }
ok(await page.evaluate(() => window.__demoApi.drawings.filter((d) => d.ticker === 'CSCO' && d.source === 'tv').every((d) => d.status === 'deleted')), 'TV drawings soft-deleted (status=deleted)');
ok((await page.locator('.card[data-id]').count()) === 0, 'deleted rows hidden');
// + zone: tap two levels
await page.tap('#addZone');
await page.touchscreen.tap(X - 60, box.y + box.height * 0.50);
await page.touchscreen.tap(X - 60, box.y + box.height * 0.58);
await page.waitForSelector('.card[data-id]');
ok((await page.locator('.card[data-id]').count()) === 1, 'zone created by 2 taps');
// + long: entry then stop
await page.tap('#addLong');
await page.touchscreen.tap(X + 40, box.y + box.height * 0.47);
await page.touchscreen.tap(X + 40, box.y + box.height * 0.60);
await page.waitForFunction(() => document.querySelectorAll('.card[data-id]').length === 2);
ok(true, 'long created by 2 taps');
// drag the target handle up (pointer events)
const h = page.locator('g.h[data-key="target"] circle').nth(1);
const hb = await h.boundingBox();
const before = await page.evaluate(() => [...window.__srs.S.drawings.values()].find((d) => d.ticker === 'CSCO' && d.kind === 'long' && d.status !== 'deleted').target);
await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
await page.mouse.down();
await page.mouse.move(hb.x + hb.width / 2, hb.y - 30, { steps: 6 });
await page.mouse.up();
await page.waitForTimeout(200);
const after = await page.evaluate(() => [...window.__srs.S.drawings.values()].find((d) => d.ticker === 'CSCO' && d.kind === 'long' && d.status !== 'deleted').target);
ok(after > before, `drag target ${before} -> ${after}`);
const rrTxt = await page.locator('.card .rr').first().textContent();
ok(/R:R \d/.test(rrTxt), 'live R:R ' + rrTxt);
// realtime from "another client": bot drawing appears via change feed
await page.evaluate(() => window.__srs.api.insertDrawing({ ticker: 'CSCO', kind: 'zone', zone_top: 80, zone_bottom: 78.5, t_start: '2026-04-06', source: 'bot', status: 'review', note: 'BOT - review needed' }));
await page.waitForFunction(() => document.querySelectorAll('.card[data-id]').length === 3);
ok(true, 'realtime insert rendered');
await page.locator('.card.bot .act[data-act="approve"]').tap();
ok(await page.evaluate(() => [...window.__srs.S.drawings.values()].some((d) => d.source === 'bot' && d.status === 'approved')), 'approve bot drawing');
// labels + command
ok(await page.locator('.lab[data-v]').count() === 0 && await page.locator('.card input[data-f]').count() === 0, 'no technical yes/no buttons, no level inputs (zone / Long edited on the chart)');
await page.fill('#cmd', 'תבדוק את האזור'); await page.tap('#sendCmd');
await page.waitForSelector('.cmds li');
ok(true, 'command sent');
// select the long so its handles show, then screenshot
await page.evaluate(() => { const S = window.__srs.S; S.selected = [...S.drawings.values()].find((d) => d.ticker === 'CSCO' && d.kind === 'long' && d.status !== 'deleted').id; });
await page.locator('.card[data-id] .selbtn').first().tap(); // zone selected -> handles
await page.waitForTimeout(2800); // let the toast fade
await page.screenshot({ path: `${OUT}/04_chart_zone_long.png` });
await page.locator('.panel').evaluate((p) => p.scrollTo(0, 99999)); await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/05_chart_panel.png` });
// daily toggle
await page.tap('[data-tf="D"]'); await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/06_chart_daily.png` });
// prev/next (clear the search/chip so the nav list has neighbours)
await page.evaluate(() => { window.__srs.S.ui.q = ''; window.__srs.S.ui.chip = 'all'; });
const t0 = await page.locator('#tk').textContent();
await page.tap('#next'); await page.waitForTimeout(500);
const t1 = await page.locator('#tk').textContent();
ok(t0 !== t1, `next ${t0} -> ${t1}`);
// swipe on header (touch events)
await page.evaluate(() => {
  const el = document.getElementById('chhead');
  const mk = (type, x) => new TouchEvent(type, { bubbles: true, touches: type === 'touchend' ? [] : [new Touch({ identifier: 1, target: el, clientX: x, clientY: 30 })], changedTouches: [new Touch({ identifier: 1, target: el, clientX: x, clientY: 30 })] });
  el.dispatchEvent(mk('touchstart', 300)); el.dispatchEvent(mk('touchend', 100));
});
await page.waitForTimeout(500);
const t2 = await page.locator('#tk').textContent();
ok(t2 !== t1, `swipe ${t1} -> ${t2}`);
// a TV-drawn ticker
// watchlist: header star + add any ticker by symbol
await page.evaluate(() => { location.hash = '#/t/CSCO'; }); await page.waitForFunction(() => document.getElementById('tk')?.textContent === 'CSCO'); await page.waitForTimeout(300);
await page.tap('#star');
ok(await page.evaluate(() => window.__srs.S.watch.has('CSCO')), 'star adds CSCO to watchlist');
// 'לא מתאימה לשיטה' (8 weeks default)
await page.locator('#niOn').tap();
ok(await page.evaluate(() => window.__srs.S.labels.some((l) => l.label === 'not_interesting' && l.value === 'yes' && l.until)), 'not_interesting label with until');
await page.screenshot({ path: `${OUT}/10_not_interesting_panel.png` });
await page.tap('#back'); await page.waitForSelector('.row');
await page.evaluate(() => { window.__srs.S.ui.q = ''; });
await page.tap('.chip[data-chip="all"]');
ok((await page.locator('.row[data-t="CSCO"]').count()) === 0, 'not-interesting hidden from main list');
await page.tap('.chip[data-chip="ni"]');
ok((await page.locator('.row[data-t="CSCO"] .b-ni').count()) === 1, "shown with badge under 'לא מתאימות לשיטה'");
await page.tap('.chip[data-chip="all"]');
await page.fill('#q', 'ZZZQ'); await page.waitForSelector('#addWatch');
await page.screenshot({ path: `${OUT}/11_add_watch.png` });
await page.tap('#addWatch');
await page.waitForSelector('#nodata:not([hidden])');
ok(await page.evaluate(() => window.__srs.S.watch.has('ZZZQ')), 'typed ticker added to watchlist; no-data message shown');
await page.screenshot({ path: `${OUT}/12_no_data.png` });
await page.tap('#back'); await page.waitForSelector('.chip');
await page.tap('.chip[data-chip="watch"]');
ok((await page.locator('.row').count()) === 2, 'watch chip lists CSCO + ZZZQ');
await page.screenshot({ path: `${OUT}/13_watch_list.png` });
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
