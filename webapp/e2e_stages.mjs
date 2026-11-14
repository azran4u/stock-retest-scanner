// Weinstein stages page (#/stages, Eyal 2026-11-13; retest-like layout 2026-11-14): demo mode at desktop 1280x900 and
// phone 390x844. Desktop: list on the right (mini chart + stage / tags / R:R / SL% / shares / rules) + the selected
// stock's big weekly chart; phone: list -> stock page -> back. Tabs (Buy-Stop candidates / 2A / 1-4 / no volume) filter,
// SL% sort works, dragging the base ceiling on the big chart saves his level ('הרמות שלך') and the R:R / SL% follow his
// trade bar, no horizontal overflow, back returns to the retest list.
// Usage: node e2e_stages.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/stages_shots';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
// a stock with computed support / resistance lines (overhead resistances + valid swing low) for the lines test
const SD = JSON.parse(readFileSync(new URL('../app/data/stages.json', import.meta.url)));
const LT = SD.rows.find((r) => r.plan && (r.plan.ov_levels || []).length >= 1 && r.plan.swing_low != null && r.plan.stop_basis === 'low')?.t;
const browser = await chromium.launch();
for (const [name, vp, mobile] of [['desktop', { width: 1280, height: 900 }, false], ['mobile', { width: 390, height: 844 }, true]]) {
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: 'he-IL' });
  const page = await ctx.newPage(); const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1'); await page.evaluate(() => localStorage.removeItem('srs-stages-ui'));
  await page.waitForSelector('#stagesLink'); await page.waitForTimeout(400);
  await page.click('#stagesLink'); await page.waitForSelector('[data-tab="bs"]');
  ok(page.url().includes('#/stages'), `${name}: link opens #/stages`);
  ok(await page.locator('.mkts .mk').count() === 3, `${name}: SPY / QQQ / IWM stage shown`);
  ok(await page.locator('[data-tab="bs"].on').count() === 1, `${name}: Buy-Stop candidates tab first + default`);
  const nbs = await page.locator('li[data-st]').count();
  const cbs = +(await page.locator('[data-tab="bs"] .cnt').innerText());
  ok(nbs === Math.min(cbs, 80), `${name}: Buy-Stop tab lists ${nbs} (count ${cbs})`);
  await page.screenshot({ path: `${OUT}/${name}_bs.png` });
  for (const s of ['1', '2', '3', '4']) {
    await page.click(`[data-tab="${s}"]`); await page.waitForTimeout(250);
    const b = await page.$$eval('li[data-st] .r1 .badge.st', (x) => x.map((e) => e.className));
    ok(b.length > 0 && b.every((c) => c.includes('st' + s)), `${name}: tab stage ${s} (${b.length} rows)`);
  }
  await page.click('[data-tab="2"]'); await page.waitForTimeout(250);
  await page.selectOption('#stsort', 'sl_asc'); await page.waitForTimeout(300);
  const sls = await page.$$eval('li[data-st]', (cs) => cs.map((c) => parseFloat([...c.querySelectorAll('.skv')].find((k) => k.textContent.startsWith('SL'))?.querySelector('b')?.textContent || 'NaN')).filter((v) => !Number.isNaN(v)));
  ok(sls.length > 3 && sls.every((v, i) => i === 0 || v >= sls[i - 1]), `${name}: sort by SL% ascending (${sls.slice(0, 4).join(', ')} …)`);
  ok(await page.$$eval('canvas.stchart', (c) => c.slice(0, 2).every((x) => x.dataset.drawn === '1')), `${name}: mini charts drawn`);
  await page.screenshot({ path: `${OUT}/${name}_list_stage2.png` });
  // open one stock (2: first row)
  const first = await page.$eval('li[data-st]', (e) => e.dataset.st);
  await page.click(`li[data-st="${first}"]`);
  await page.waitForSelector('#stbig canvas'); await page.waitForTimeout(900);
  ok(page.url().includes('#/stages/' + first), `${name}: row opens #/stages/${first}`);
  ok(await page.locator('.stpanel .cks li').count() >= 8, `${name}: plan + checks shown`);
  if (!mobile) ok(await page.locator('#stSide li[data-st].sel').count() === 1, `${name}: list stays on the right with the row selected`);
  await page.screenshot({ path: `${OUT}/${name}_detail.png` });
  // select the computed zone (tag) and drag its top handle up -> saved as his level
  const tag = page.locator('#stbig svg.overlay g.tag').first();
  await tag.click({ force: true }); await page.waitForTimeout(300);
  const h = page.locator('#stbig svg.overlay g.h[data-k="zone_top"], #stbig svg.overlay g.h').first();
  const bb = await h.boundingBox();
  if (bb) {
    const x = bb.x + bb.width / 2, y = bb.y + bb.height / 2;
    await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x, y - 25, { steps: 6 }); await page.mouse.up();
    await page.waitForTimeout(700);
  }
  const saved = await page.evaluate(() => window.__demoApi.stageDrawings.length);
  ok(saved === 1 && await page.locator('.sttags.pad .badge.b-his').count() === 1, `${name}: drag saves his level (stage_drawings ${saved})`);
  ok(await page.locator('#streset').count() === 1, `${name}: reset to computed offered`);
  await page.screenshot({ path: `${OUT}/${name}_edited.png` });
  await page.click('#streset'); await page.waitForTimeout(500);
  ok(await page.locator('.sttags.pad .badge.b-his').count() === 0, `${name}: reset back to computed levels`);
  ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow (detail)`);
  if (mobile) {
    await page.click('#stback'); await page.waitForSelector('li[data-st]');
    ok(!/#\/stages\//.test(page.url()), `${name}: back to the stages list`);
    ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow (list)`);
  }
  // support / resistance lines (Eyal 2026-11-14): labelled, drag = his level (target recomputed), delete, add, reset
  if (mobile) { await page.click(`li[data-st]`); await page.waitForSelector('#stbig canvas'); await page.waitForTimeout(400); }
  await page.evaluate((t) => { location.hash = '#/stages/' + t; }, LT);
  await page.waitForFunction((t) => location.hash === '#/stages/' + t && document.querySelector('#stbig svg.overlay g.lhit'), LT);
  await page.waitForTimeout(700);
  const nl0 = await page.locator('#stbig svg.overlay g.lhit').count();
  const labs = await page.$$eval('#stbig svg.overlay g.tag text', (x) => x.map((e) => e.textContent).join(' | '));
  ok(nl0 >= 2 && labs.includes('התנגדות תקורה') && labs.includes('תמיכה – שפל תקף') && labs.includes('תקרת בסיס'), `${name}: ${LT} lines labelled (${nl0}: ${labs.slice(0, 120)}…)`);
  const tgtTxt = async () => page.$eval('.stpanel .skv:nth-child(3) b', (e) => e.textContent);
  const t0 = await tgtTxt();
  await page.locator('#stbig svg.overlay g.lhit[data-sel="c-ov0"]').click({ force: true }); await page.waitForTimeout(300);
  ok(await page.locator('#stdelline').count() === 1, `${name}: selecting a line offers delete`);
  const lh = await page.locator('#stbig svg.overlay g.h[data-id="c-ov0"]').boundingBox();
  if (lh) { const x = lh.x + lh.width / 2, y = lh.y + lh.height / 2; await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x, y - 30, { steps: 6 }); await page.mouse.up(); await page.waitForTimeout(700); }
  const t1 = await tgtTxt();
  ok(await page.evaluate(() => window.__demoApi.stageDrawings.filter((x) => x.kind === 'line' && x.status === 'active').length) === 1 && t1 !== t0 && await page.locator('.sttags.pad .badge.b-his').count() === 1,
    `${name}: dragging the overhead line saves his level, target ${t0} -> ${t1}`);
  await page.click('#stdelline'); await page.waitForTimeout(500);
  ok(await page.locator('#stbig svg.overlay g.lhit').count() === nl0 - 1, `${name}: delete removes the line`);
  await page.click('#staddline'); await page.waitForTimeout(200);
  const cb = await page.locator('#stbig').boundingBox();
  await page.mouse.click(cb.x + cb.width * 0.3, cb.y + cb.height * 0.12); await page.waitForTimeout(700);
  ok(await page.locator('#stbig svg.overlay g.lhit').count() === nl0, `${name}: '+ קו' adds his line`);
  await page.screenshot({ path: `${OUT}/${name}_lines.png` });
  await page.click('#streset'); await page.waitForTimeout(600);
  ok(await page.locator('#stbig svg.overlay g.lhit').count() === nl0 && await page.locator('.sttags.pad .badge.b-his').count() === 0 && (await tgtTxt()) === t0, `${name}: reset -> computed lines + target again`);
  ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow (lines)`);
  if (mobile) { await page.click('#stback'); await page.waitForSelector('li[data-st]'); }
  await page.click('#strulesBtn'); await page.waitForTimeout(200);
  ok((await page.locator('.strulesheet').innerText()).includes('שמיים פתוחים'), `${name}: rules shown`);
  await page.click('#strulesClose');
  await page.click('#stHome'); await page.waitForTimeout(500);
  ok(!page.url().includes('#/stages'), `${name}: back leaves the page`);
  ok(!errors.length, `${name}: no page errors ${errors.join(' | ')}`);
  await ctx.close();
}
await browser.close();
