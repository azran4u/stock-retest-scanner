// Lives archive page (#/lives): search, sort, filters, RTL, phone + desktop.
// Demo mode; data injected via window.__demoLives (not shipped in the build).
// Usage: node e2e_lives.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync, readFileSync, existsSync } from 'node:fs';
import { dirname } from 'node:path';

const BASE = process.argv[2] || 'http://localhost:5173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/lives';
mkdirSync(OUT, { recursive: true });
const jsonPath = '/workspace/lives/lives.json';
if (!existsSync(jsonPath)) { console.log('FAIL missing', jsonPath); process.exit(1); }
const lives = JSON.parse(readFileSync(jsonPath, 'utf8'));

const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

function newestDate(rows) {
  return rows.slice().sort((a, b) => (b.display_date || '').localeCompare(a.display_date || ''))[0].display_date;
}
function fmt(iso) {
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

const browser = await chromium.launch();
for (const [name, vp, mobile] of [
  ['desktop', { width: 1280, height: 900 }, false],
  ['mobile', { width: 390, height: 844 }, true],
]) {
  const ctx = await browser.newContext({
    viewport: vp, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: 'he-IL',
  });
  await ctx.addInitScript((rows) => { window.__demoLives = rows; }, lives);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));

  // auth gate: demo=login must not reveal the archive
  await page.goto(BASE + '?demo=login#/lives', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#google, .login');
  ok(await page.locator('#google').count() === 1, `${name}: unauthenticated #/lives shows Google login`);
  ok(await page.locator('.lives-table, #lvQ').count() === 0, `${name}: unauthenticated page has no lives table or search`);

  await page.goto(BASE + '?demo=1#/lives', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#lvBody, .lives-table, .lv-row', { timeout: 15000 });
  await page.waitForFunction(() => document.querySelectorAll('.lv-row').length > 0);

  ok(await page.evaluate(() => document.documentElement.dir === 'rtl' && document.documentElement.lang === 'he'), `${name}: html is he/rtl`);
  ok(page.url().includes('#/lives'), `${name}: hash is #/lives`);

  const controls = await page.evaluate(() => ['lvQ', 'lvMentor', 'lvArchive', 'lvSum', 'lvSort', 'lvBack'].every((id) => document.getElementById(id)));
  ok(controls, `${name}: search, mentor, archive, has-summary, sort, back are all present`);

  const countText = await page.locator('#lvCount').innerText();
  ok(countText.includes(String(lives.length)), `${name}: count shows ${lives.length} (${countText})`);

  const firstDate = await page.locator('.lv-row .lv-date').first().innerText();
  ok(firstDate.trim() === fmt(newestDate(lives)), `${name}: default sort newest first (got ${firstDate}, want ${fmt(newestDate(lives))})`);

  // search by ticker
  await page.fill('#lvQ', 'AAPL');
  await page.waitForTimeout(200);
  const aapl = await page.evaluate(() => [...document.querySelectorAll('.lv-row')].map((r) => r.innerText));
  ok(aapl.length > 0 && aapl.length < lives.length && aapl.every((t) => t.toUpperCase().includes('AAPL')), `${name}: search AAPL -> ${aapl.length} rows, all mention AAPL`);

  // search by mentor name
  await page.fill('#lvQ', 'שגיא');
  await page.waitForTimeout(200);
  const sagi = await page.evaluate(() => [...document.querySelectorAll('.lv-row .lv-mentor')].map((r) => r.innerText.trim()));
  ok(sagi.length > 0 && sagi.every((m) => m === 'שגיא' || m.includes('שגיא')), `${name}: search שגיא -> ${sagi.length}, mentors=${[...new Set(sagi)].join(',')}`);

  await page.fill('#lvQ', '');
  await page.waitForTimeout(150);

  // mentor filter
  await page.selectOption('#lvMentor', 'רז');
  await page.waitForTimeout(150);
  const raz = await page.evaluate(() => [...document.querySelectorAll('.lv-row .lv-mentor')].map((r) => r.innerText.trim()));
  const razN = lives.filter((r) => r.mentor === 'רז').length;
  ok(raz.length === razN && raz.every((m) => m === 'רז'), `${name}: mentor רז filter -> ${raz.length} (want ${razN})`);
  await page.selectOption('#lvMentor', '');

  // archive filter
  await page.selectOption('#lvArchive', 'students');
  await page.waitForTimeout(150);
  const stuN = lives.filter((r) => r.archive === 'students').length;
  const stu = await page.locator('.lv-row').count();
  ok(stu === stuN, `${name}: archive students -> ${stu} (want ${stuN})`);
  await page.selectOption('#lvArchive', '');

  // has-summary
  await page.selectOption('#lvSum', 'yes');
  await page.waitForTimeout(150);
  const sumN = lives.filter((r) => r.summary_link).length;
  const sumC = await page.locator('.lv-row').count();
  const sumLinks = await page.locator('.lv-row a.lv-link[href*="cyclestrading.com"]').count();
  ok(sumC === sumN && sumLinks === sumN, `${name}: has-summary -> ${sumC} rows and ${sumLinks} summary links (want ${sumN})`);
  await page.selectOption('#lvSum', '');

  // sort by mentor
  await page.selectOption('#lvSort', 'mentor');
  await page.waitForTimeout(150);
  const mentors = await page.evaluate(() => [...document.querySelectorAll('.lv-row .lv-mentor')].map((r) => r.innerText.trim()));
  const sorted = mentors.slice().sort((a, b) => a.localeCompare(b, 'he'));
  ok(mentors.length === lives.length && mentors[0] === sorted[0] && mentors.join('\n') === sorted.join('\n'), `${name}: sort by mentor is Hebrew-alphabetical`);

  // links
  const linkInfo = await page.evaluate(() => {
    const rec = document.querySelector('.lv-row a.lv-link[href*="youtu"]');
    return rec ? { href: rec.getAttribute('href'), target: rec.getAttribute('target'), rel: rec.getAttribute('rel') || '' } : null;
  });
  ok(linkInfo && linkInfo.target === '_blank' && linkInfo.rel.includes('noopener'), `${name}: recording link is clickable and opens a new tab`);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  ok(overflow, `${name}: no horizontal overflow (scrollWidth vs innerWidth)`);

  await page.selectOption('#lvSort', 'date');
  await page.selectOption('#lvMentor', '');
  await page.selectOption('#lvArchive', '');
  await page.selectOption('#lvSum', '');
  await page.fill('#lvQ', '');
  await page.waitForTimeout(200);
  const shot = name === 'desktop' ? `${OUT}/lives_page.png` : `${OUT}/lives_page_mobile.png`;
  await page.screenshot({ path: shot, fullPage: false });
  console.log('shot', shot);

  // back
  await page.click('#lvBack');
  await page.waitForTimeout(400);
  ok(!page.url().includes('#/lives'), `${name}: back leaves #/lives`);
  // nav link from the list
  await page.waitForSelector('#livesLink', { timeout: 15000 });
  await page.click('#livesLink');
  await page.waitForSelector('.lv-row, #lvBody');
  ok(page.url().includes('#/lives'), `${name}: header לייבים link opens the page`);

  ok(!errors.length, `${name}: no page errors ${errors.join(' | ')}`);
  await ctx.close();
}
await browser.close();
if (process.exitCode) console.log('FAILED'); else console.log('all e2e ok');
