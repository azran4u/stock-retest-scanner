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
const zf = (r) => (r.bo && r.sub === '2A' ? r.bo.base_low : r.base ? r.base.low : r.range?.floor);
const LT = (SD.rows.find((r) => r.plan && (r.plan.ov_levels || []).length >= 1 && r.plan.swing_low != null && Math.abs(zf(r) / r.plan.swing_low - 1) < 0.003)
  || SD.rows.find((r) => r.plan && (r.plan.ov_levels || []).length >= 1 && r.plan.swing_low != null))?.t;
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
  // two solid lines, no labels (Eyal 2026-11-14): BLUE = resistance (base ceiling / Buy-Stop), RED = support (stop basis)
  await page.evaluate((t) => { location.hash = '#/stages/' + t; }, LT);
  await page.waitForFunction((t) => location.hash === '#/stages/' + t && document.querySelectorAll('#stbig svg.overlay g.lhit').length === 2, LT);
  await page.waitForTimeout(700);
  const lines = await page.$$eval('#stbig svg.overlay line', (ls) => ls.map((l) => [l.getAttribute('stroke'), l.getAttribute('stroke-dasharray')]));
  const blue = lines.filter(([c]) => c === '#2962ff'), red = lines.filter(([c]) => c === '#ef5350' );
  const labs = await page.$$eval('#stbig svg.overlay g.tag text', (x) => x.map((e) => e.textContent).join(' | '));
  ok(blue.length === 1 && !blue[0][1] && red.length >= 1 && red.every(([, d]) => !d) && !/התנגדות|תמיכה/.test(labs), `${name}: ${LT} = one solid blue + one solid red line, no labels (${labs})`);
  const kvTxt = async (k) => page.$$eval('.stpanel .skv', (xs, k) => xs.find((x) => x.querySelector('span').textContent.startsWith(k))?.querySelector('b').textContent, k);
  const drag = async (id, dy) => {
    await page.locator(`#stbig svg.overlay g.lhit[data-sel="${id}"]`).click({ force: true }); await page.waitForTimeout(300);
    const hb = await page.locator(`#stbig svg.overlay g.h[data-id="${id}"]`).boundingBox();
    if (hb) { const x = hb.x + hb.width / 2, y = hb.y + hb.height / 2; await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x, y + dy, { steps: 6 }); await page.mouse.up(); await page.waitForTimeout(700); }
  };
  const bs0 = await kvTxt('Buy-Stop'), sl0 = await kvTxt('SL');
  await drag('c-sup', -12);
  const sl1 = await kvTxt('SL');
  ok(sl1 !== sl0 && await page.locator('.sttags.pad .badge.b-his').count() === 1, `${name}: dragging the red line moves the SL ${sl0} -> ${sl1}`);
  await drag('c-res', -160);
  const bs1 = await kvTxt('Buy-Stop');
  ok(bs1 !== bs0, `${name}: dragging the blue line moves the Buy-Stop ${bs0} -> ${bs1}`);
  const pr = await page.evaluate(() => window.__stCv?.chart.priceScale('right').getVisibleRange());
  ok(pr && pr.from >= 0, `${name}: price axis fits candles + levels, not below 0 (${pr && pr.from.toFixed(2)}–${pr && pr.to.toFixed(2)})`);
  await page.screenshot({ path: `${OUT}/${name}_lines.png` });
  await page.click('#streset'); await page.waitForTimeout(600);
  ok(await page.locator('.sttags.pad .badge.b-his').count() === 0 && (await kvTxt('Buy-Stop')) === bs0 && (await kvTxt('SL')) === sl0, `${name}: reset -> computed lines again`);
  await page.locator('#stbig svg.overlay g.lhit').first().click({ force: true }); await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT}/${name}_stock.png` });
  ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow (lines)`);
  // sector ETF page (Eyal 2026-11-14): the stock page's sector badge opens #/stages/ETF, back returns to the stock
  const ETF = SD.rows.find((r) => r.t === LT)?.etf;
  await page.click('.stname a.etfl'); await page.waitForFunction((e) => location.hash === '#/stages/' + e && document.querySelector('#stbig canvas'), ETF);
  await page.waitForTimeout(900);
  const rule = await page.locator('#secrule').innerText();
  ok(/כלל הסקטור/.test(rule) && /שלב 2 מובהק|סוף שלב 1 – התעוררות|שלב 3|שלב 4|לא עומד/.test(rule) && await page.locator('.stpanel .cks li').count() >= 4, `${name}: ${LT} -> sector ${ETF} chart + rule (${rule})`);
  ok(await page.evaluate(() => !!window.__stCv && window.__stCv.chart.priceScale('right').getVisibleRange().from >= 0), `${name}: ${ETF} candles drawn`);
  await page.screenshot({ path: `${OUT}/${name}_etf_${ETF}.png` });
  await page.click('#stback'); await page.waitForFunction((t) => location.hash === '#/stages/' + t, LT);
  ok(true, `${name}: back from ${ETF} returns to ${LT}`);
  await page.waitForSelector('#stbig canvas');
  if (mobile) { await page.click('#stback'); await page.waitForSelector('li[data-st]'); }
  // card chip -> ETF; XLU from the sector table
  const chip = page.locator('li[data-st] button.etfl').first();
  const chipEtf = await chip.getAttribute('data-etf'), chipT = await page.locator('li[data-st]').first().getAttribute('data-st');
  await chip.click(); await page.waitForFunction((e) => location.hash === '#/stages/' + e, chipEtf); await page.waitForTimeout(500);
  ok((await page.locator('#stback').getAttribute('href')) === '#/stages/' + chipT, `${name}: card chip opens ${chipEtf}, back -> ${chipT}`);
  if (mobile) { await page.click('#stback'); await page.waitForTimeout(400); await page.click('#stback'); await page.waitForSelector('li[data-st]'); }
  await page.locator('details.secs summary').click(); await page.waitForTimeout(200);
  await page.locator('details.secs a.etfl[data-etf="XLU"]').click(); await page.waitForFunction(() => location.hash === '#/stages/XLU'); await page.waitForTimeout(800);
  ok((await page.locator('#secrule').innerText()).includes('סוף שלב 1 – התעוררות'), `${name}: XLU = late stage 1 / awakening`);
  ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: no horizontal overflow (ETF)`);
  await page.screenshot({ path: `${OUT}/${name}_etf_XLU.png` });
  if (mobile) { await page.click('#stback'); await page.waitForTimeout(400); if (/#\/stages\//.test(page.url())) { await page.click('#stback'); } await page.waitForSelector('li[data-st]'); }
  await page.click('#strulesBtn'); await page.waitForTimeout(200);
  ok((await page.locator('.strulesheet').innerText()).includes('שמיים פתוחים'), `${name}: rules shown`);
  await page.click('#strulesClose');
  await page.click('#stHome'); await page.waitForTimeout(500);
  ok(!page.url().includes('#/stages'), `${name}: back leaves the page`);
  ok(!errors.length, `${name}: no page errors ${errors.join(' | ')}`);
  await ctx.close();
}
await browser.close();
