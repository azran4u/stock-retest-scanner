// Roi analysis badges, filter, and detail panel. Demo mode; data injected via window.__demoRoi
// (not shipped in the build). Usage: node e2e_roi.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = process.argv[2] || 'http://127.0.0.1:4175/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/roi';
mkdirSync(OUT, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

const FIXTURE = [
  {
    ticker: 'AAL',
    recommendation: 'כניסה עכשיו / להציב פקודת לימיט',
    entry: 11.93, stop: 10.72, target: 18.79, rr: 5.67,
    rationale_he: 'המגמה השבועית עולה; תוכנית העבודה של רועי.',
    checklist: [
      { item: 'מגמה ראשית שבועית/חודשית', result: '✔', detail: 'עולה' },
      { item: 'אישור / סימן היפוך', result: '✖', detail: 'אין אישור' },
    ],
    roi_mentions: [{ date: '2026-10-01', source: 'דף סיכום לייב', quote: 'נראית חיובית עם קו מגמה יפה' }],
    as_of: '2026-11-23', trigger_he: 'חזרה לאזור',
  },
  {
    ticker: 'NOW',
    recommendation: 'לחכות לאישור (מה הטריגר)',
    entry: 70, stop: 65, target: 90, rr: 4,
    rationale_he: 'לחכות לאישור שבועי.',
    checklist: [{ item: 'אישור / סימן היפוך', result: '✖', detail: 'עדיין אין' }],
    roi_mentions: [], as_of: '2026-11-23',
  },
];

const browser = await chromium.launch();
for (const [name, vp, mobile] of [
  ['desktop', { width: 1280, height: 900 }, false],
  ['mobile', { width: 390, height: 844 }, true],
]) {
  const ctx = await browser.newContext({
    viewport: vp, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: 'he-IL',
  });
  await ctx.addInitScript((rows) => { window.__demoRoi = rows; }, FIXTURE);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const qs = name === 'desktop' ? '?demo=1' : '?demo=1&nosplit=1';
  await page.goto(BASE + qs, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.row', { timeout: 20000 });
  await page.waitForFunction(() => window.__srs?.S?.loaded && window.__srs?.S?.roi, { timeout: 15000 });


  ok(await page.evaluate(() => document.documentElement.dir === 'rtl' && document.documentElement.lang === 'he'), `${name}: he/rtl`);

  // default 'unfit: hide' would drop AAL/NOW (no long plan). Show all so the Roi overlay can be tested.
  const openFilters = async () => {
    const tog = page.locator('#ftog');
    if (await tog.count()) {
      const open = await page.locator('#fpanel').isVisible().catch(() => false);
      if (!open) await tog.click();
      await page.waitForSelector('#fpanel', { state: 'visible', timeout: 5000 });
    }
  };
  await openFilters();
  const unfitAll = page.locator('.fi[data-f="unfit"] button.seg[data-mode="all"]');
  if (await unfitAll.count()) await unfitAll.click();
  await page.waitForTimeout(200);

  // badge visible for AAL on the list (may need search)
  await page.fill('#q', 'AAL');
  await page.waitForTimeout(300);
  const aalBadge = await page.locator('.row[data-t="AAL"] .badge.b-roi-enter').count();
  const aalText = aalBadge ? await page.locator('.row[data-t="AAL"] .badge.b-roi-enter').innerText() : '';
  ok(aalBadge === 1 && aalText.includes('כניסה עכשיו') && /5\.67/.test(aalText), `${name}: AAL list badge (${aalText})`);

  await page.fill('#q', 'NOW');
  await page.waitForTimeout(300);
  const cscoBadge = await page.locator('.row[data-t="NOW"] .badge.b-roi-wait').innerText().catch(() => '');
  ok(cscoBadge.includes('לחכות לאישור') && cscoBadge.includes('4.00'), `${name}: NOW wait badge (${cscoBadge})`);

  // a ticker without Roi data: no badge (use first other visible? search a known pass without fixture)
  await page.fill('#q', '');
  await page.waitForTimeout(200);
  const noBadge = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.row')].filter((r) => !['AAL', 'NOW'].includes(r.getAttribute('data-t') || ''));
    const hit = rows.find((r) => !r.querySelector('.badge.b-roi'));
    return hit ? hit.getAttribute('data-t') : null;
  });
  ok(!!noBadge, `${name}: some list row has no Roi badge (${noBadge})`);

  // recommendation filter
  await openFilters();
  const recSel = page.locator('.fi[data-f="roiRec"] .fsel');
  ok(await recSel.count() === 1, `${name}: recommendation filter is present`);
  await recSel.selectOption('enter');
  await page.waitForTimeout(300);
  await page.fill('#q', '');
  await page.waitForTimeout(200);
  const only = await page.evaluate(() => [...document.querySelectorAll('.row')].map((r) => r.getAttribute('data-t')));
  ok(only.includes('AAL') && !only.includes('NOW') && only.every((t) => t), `${name}: enter filter keeps AAL, drops NOW (${only.join(',')})`);

  // detail panel (close the mobile filter sheet first — it covers the list and #ftog)
  const done = page.locator('#fdone');
  if (await done.isVisible().catch(() => false)) {
    await done.click();
    await page.locator('#fpanel').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
  }
  await page.evaluate(() => { location.hash = '#/t/AAL'; });
  await page.waitForSelector('#roiPanel', { timeout: 15000 });
  const panel = await page.locator('#roiPanel').innerText();
  ok(panel.includes('ניתוח רועי') && panel.includes('שיטת רועי') && panel.includes('המגמה השבועית עולה') && panel.includes('נראית חיובית') && panel.includes('01.10.2026') && panel.includes('דף סיכום לייב'), `${name}: detail panel content`);
  ok(await page.evaluate(() => document.getElementById('roiPanel')?.open !== false), `${name}: panel is expandable and open`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  ok(overflow, `${name}: no horizontal overflow`);

  if (name === 'desktop') {
    await page.screenshot({ path: `${OUT}/roi_page.png`, fullPage: false });
    console.log('shot', `${OUT}/roi_page.png`);
  } else {
    await page.screenshot({ path: `${OUT}/roi_page_mobile.png`, fullPage: false });
    console.log('shot', `${OUT}/roi_page_mobile.png`);
  }

  // ticker without data: no panel
  // go back to list if needed
  const back = page.locator('#back, header.ch .ghost, a[href="#/"]');
  // open a no-roi ticker via hash
  if (noBadge) {
    await page.evaluate((t) => { location.hash = '#/t/' + t; }, noBadge);
    await page.waitForTimeout(800);
    ok(await page.locator('#roiPanel').count() === 0, `${name}: no Roi panel on ${noBadge}`);
  }

  ok(!errors.length, `${name}: no page errors ${errors.join(' | ')}`);
  await ctx.close();
}
await browser.close();
if (process.exitCode) console.log('FAILED'); else console.log('all e2e ok');
