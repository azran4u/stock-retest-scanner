// Stages chart drawing tools (Eyal t455u): Long/Short position, horizontal line, draggable S/R,
// persist per ticker (demo: localStorage; production: public.stage_drawings). Reload must keep the drawings.
// Usage: node e2e_stages_tools.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';

const BASE = process.argv[2] || 'http://127.0.0.1:4174/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/stages_shots/v7';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

const SD = JSON.parse(readFileSync(new URL('../app/data/stages.json', import.meta.url)));
const T = (SD.rows.find((r) => r.plan && r.plan.swing_low != null && (r.base || r.bo)) || SD.rows.find((r) => r.plan))?.t;
if (!T) { console.log('FAIL no stock with a Buy-Stop plan in stages.json'); process.exit(1); }

const kvTxt = async (page, k) => page.$$eval('.stpanel .skv', (xs, k) => xs.find((x) => x.querySelector('span')?.textContent.startsWith(k))?.querySelector('b')?.textContent, k);
const dragHandle = async (page, sel, dy) => {
  const loc = page.locator(sel).first();
  await loc.waitFor({ timeout: 8000 });
  const hb = await loc.boundingBox();
  if (!hb) throw new Error('no box for ' + sel);
  const x = hb.x + hb.width / 2, y = hb.y + hb.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + dy, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(800);
};
const tapChart = async (page, fracY) => {
  const box = await page.locator('#stbig').boundingBox();
  ok(!!box, 'chart pane has a box');
  await page.mouse.click(box.x + box.width * 0.42, box.y + box.height * fracY);
  await page.waitForTimeout(600);
};

const run = async (name, vp, touch) => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: touch ? 2 : 1, hasTouch: !!touch, isMobile: name === 'phone', locale: 'he-IL' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(BASE + '?demo=1');
  await page.evaluate(() => {
    localStorage.removeItem('srs-stages-ui');
    localStorage.removeItem('srs-demo-stage-drawings');
  });
  await page.goto(BASE + '?demo=1#/stages/' + encodeURIComponent(T));
  await page.waitForSelector('#stbig canvas');
  await page.waitForTimeout(1100);

  ok(await page.locator('#sttool-long').count() === 1, `${name}: Long tool on the toolbar`);
  ok(await page.locator('#sttool-short').count() === 1, `${name}: Short tool on the toolbar`);
  ok(await page.locator('#sttool-hline').count() === 1, `${name}: horizontal-line tool on the toolbar`);
  ok(await page.locator('#streset').count() === 1, `${name}: reset-to-bot control present`);

  // Place a long at the bot Buy-Stop / SL / target (already drawn; the button selects it).
  await page.locator('#sttool-long').click();
  await page.waitForTimeout(400);
  const labels = await page.$$eval('#stbig svg.overlay text', (xs) => xs.map((e) => e.textContent || '').join(' | '));
  ok(/R:R/.test(labels), `${name}: position shows R:R (${labels.slice(0, 180)})`);
  ok(/מניות/.test(labels), `${name}: position shows share count for $55 risk`);
  ok(/SL\s*\$/.test(labels) || /SL /.test(labels), `${name}: position shows SL $ / %`);
  ok(await page.locator('#stbig svg.overlay g.h[data-key="stop"]').count() >= 1, `${name}: Long selected with a draggable SL handle`);

  const sl0 = await kvTxt(page, 'SL');
  await dragHandle(page, '#stbig svg.overlay g.h[data-key="stop"]', 28);
  const sl1 = await kvTxt(page, 'SL');
  ok(sl1 && sl0 && sl1 !== sl0, `${name}: dragging SL moves the stop ${sl0} -> ${sl1}`);
  const savedLong = await page.evaluate((t) => (window.__demoApi.stageDrawings || []).some((d) => d.ticker === t && d.kind === 'long' && d.status === 'active'), T);
  ok(savedLong, `${name}: dragged SL persisted as a user long in stage_drawings`);

  const nLines0 = await page.evaluate((t) => (window.__demoApi.stageDrawings || []).filter((d) => d.ticker === t && d.kind === 'line' && d.status === 'active' && !d.meta?.ref).length, T);
  await page.locator('#sttool-hline').click();
  await page.waitForTimeout(200);
  await tapChart(page, 0.28);
  const nLines1 = await page.evaluate((t) => (window.__demoApi.stageDrawings || []).filter((d) => d.ticker === t && d.kind === 'line' && d.status === 'active' && !d.meta?.ref).length, T);
  ok(nLines1 === nLines0 + 1, `${name}: adding a horizontal line saves it (${nLines0} -> ${nLines1})`);
  const lineId = await page.evaluate((t) => {
    const rows = (window.__demoApi.stageDrawings || []).filter((d) => d.ticker === t && d.kind === 'line' && d.status === 'active' && !d.meta?.ref);
    return rows[rows.length - 1]?.id || null;
  }, T);
  ok(!!lineId, `${name}: user line id ${lineId}`);
  const px0 = await page.evaluate((id) => (window.__demoApi.stageDrawings || []).find((d) => d.id === id)?.entry, lineId);
  if (await page.locator(`#stbig svg.overlay g.h[data-id="${lineId}"]`).count() === 0) {
    await page.locator(`#stbig svg.overlay g.lhit[data-sel="${lineId}"], #stbig svg.overlay g.tag[data-sel="${lineId}"]`).first().click({ force: true });
    await page.waitForTimeout(400);
  }
  await dragHandle(page, `#stbig svg.overlay g.h[data-id="${lineId}"]`, 24);
  const px1 = await page.evaluate((id) => (window.__demoApi.stageDrawings || []).find((d) => d.id === id)?.entry, lineId);
  ok(px0 != null && px1 != null && Number(px1) !== Number(px0), `${name}: moving the horizontal line ${px0} -> ${px1}`);

  const sup0 = await page.evaluate(() => {
    const el = document.querySelector('#stbig svg.overlay g.lhit[data-sel="c-sup"]');
    return el ? el.getBoundingClientRect().y : null;
  });
  // If the bot support was already replaced by a user row, drag that instead.
  const srId = await page.evaluate(() => {
    if (document.querySelector('#stbig svg.overlay g.lhit[data-sel="c-sup"]')) return 'c-sup';
    const hits = [...document.querySelectorAll('#stbig svg.overlay g.lhit')].map((e) => e.getAttribute('data-sel'));
    return hits.find((id) => id && id !== lineId) || hits[0];
  });
  ok(!!srId, `${name}: an S/R line is on the chart (${srId})`);
  if (await page.locator(`#stbig svg.overlay g.h[data-id="${srId}"]`).count() === 0) {
    await page.locator(`#stbig svg.overlay g.lhit[data-sel="${srId}"]`).click({ force: true });
    await page.waitForTimeout(300);
  }
  const srPx0 = await page.evaluate((id) => {
    const d = (window.__demoApi.stageDrawings || []).find((x) => x.id === id || (x.meta && x.meta.ref === id && x.status === 'active'));
    if (d) return d.entry;
    const line = document.querySelector(`#stbig svg.overlay g.lhit[data-sel="${id}"]`);
    return line ? line.getBoundingClientRect().y : null;
  }, srId);
  await dragHandle(page, `#stbig svg.overlay g.h[data-id="${srId}"], #stbig svg.overlay g.h`, 26);
  await page.waitForTimeout(400);
  const srSaved = await page.evaluate((t) => (window.__demoApi.stageDrawings || []).some((d) => d.ticker === t && d.kind === 'line' && d.status === 'active' && (d.meta?.ref === 'c-sup' || d.meta?.role === 'sup' || d.meta?.role === 'ceil' || d.meta?.role === 'res' || d.meta?.ref === 'c-res' || d.meta?.ref === 'c-floor')), T);
  ok(srSaved, `${name}: dragging the S/R line saved a user override`);

  await page.screenshot({ path: `${OUT}/${name}_tools.png`, animations: 'disabled' });

  // Reload: demo drawings must come back from localStorage.
  const snap = await page.evaluate((t) => (window.__demoApi.stageDrawings || []).filter((d) => d.ticker === t && d.status === 'active').map((d) => ({ kind: d.kind, entry: d.entry, stop: d.stop, target: d.target, role: d.meta?.role, ref: d.meta?.ref })), T);
  await page.reload();
  await page.waitForSelector('#stbig canvas');
  await page.waitForTimeout(1200);
  const snap2 = await page.evaluate((t) => (window.__demoApi.stageDrawings || []).filter((d) => d.ticker === t && d.status === 'active').map((d) => ({ kind: d.kind, entry: d.entry, stop: d.stop, target: d.target, role: d.meta?.role, ref: d.meta?.ref })), T);
  const longs1 = snap.filter((d) => d.kind === 'long');
  const longs2 = snap2.filter((d) => d.kind === 'long');
  ok(longs2.length === longs1.length && longs2[0] && longs2[0].stop === longs1[0].stop && longs2[0].entry === longs1[0].entry, `${name}: reload keeps the long (SL ${longs2[0]?.stop})`);
  const linesReload = snap2.filter((d) => d.kind === 'line');
  ok(linesReload.length >= snap.filter((d) => d.kind === 'line').length && linesReload.some((d) => d.entry === px1), `${name}: reload keeps the moved horizontal line at ${px1}`);
  ok(linesReload.some((d) => d.ref === 'c-sup' || d.ref === 'c-res' || d.ref === 'c-floor' || d.role === 'sup' || d.role === 'ceil' || d.role === 'res'), `${name}: reload keeps the moved S/R line`);
  const labels2 = await page.$$eval('#stbig svg.overlay text', (xs) => xs.map((e) => e.textContent || '').join(' | '));
  ok(/R:R/.test(labels2) && /מניות/.test(labels2), `${name}: after reload the position labels are back`);
  await page.screenshot({ path: `${OUT}/${name}_tools_reloaded.png`, animations: 'disabled' });

  ok(!errors.length, `${name}: no page errors ${errors.join(' | ')}`);
  await ctx.close();
  await browser.close();
};

await run('desktop', { width: 1280, height: 900 }, false);
// One mobile pass: tools must be present and the same actions work (touch context).
await run('phone', { width: 390, height: 844 }, true);

console.log('e2e_stages_tools done, ticker', T, 'exit', process.exitCode || 0);
