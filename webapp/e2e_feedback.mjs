// Bot drawing feedback smoke test (demo mode, iPhone 390x844). Usage: node e2e_feedback.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'he-IL' });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

await page.goto(BASE + '?demo=1#/t/CSCO');
await page.waitForSelector('#chart canvas'); await page.waitForTimeout(600);
// replace the demo TV rows with a bot zone + long (as srs_app.bot_drawings inserts them)
const meta = { rule_version: 'v3d-2026-10-23', why: { rule: 'v3d', branch: 'retest', pivot_date: '2026-02-27', sl_src: 'default_1atr', atr_w: 6.9 } };
await page.evaluate(async (meta) => {
  const S = window.__srs.S, api = window.__srs.api;
  for (const d of [...S.drawings.values()]) if (d.ticker === 'CSCO') await api.deleteDrawing(d.id);
  await api.insertDrawing({ ticker: 'CSCO', kind: 'zone', zone_top: 98, zone_bottom: 95, t_start: '2026-02-23', source: 'bot', status: 'active', note: 'BOT v3d', meta });
  await api.insertDrawing({ ticker: 'CSCO', kind: 'long', entry: 97.5, stop: 91, target: 118, t_start: '2026-10-26', t_end: '2027-03-15', source: 'bot', status: 'active', note: 'BOT v3d', meta });
}, meta);
await page.waitForFunction(() => document.querySelectorAll('.card[data-id]').length === 2);
ok((await page.locator('.card .fbb').count()) === 8, 'feedback buttons on both bot cards (4 each)');
ok((await page.locator('.card').first().textContent()).includes('מאושר אוטומטית'), 'bot drawing shown as active (auto-approved)');

// edit the bot long via the panel -> becomes his (source user) with bot_before
const longCard = page.locator('.card[data-id]').nth(1);
const lid = await longCard.getAttribute('data-id');
await longCard.locator('input[data-f="target"]').fill('120');
await longCard.locator('input[data-f="target"]').dispatchEvent('change');
await page.locator('#cmd').focus(); await page.waitForTimeout(200);
const ed = await page.evaluate((id) => window.__demoApi.drawings.find((d) => d.id === id), lid);
ok(ed.source === 'user' && ed.meta.bot_before.target === 118 && ed.target === 120 && ed.meta.rule_version === 'v3d-2026-10-23',
  `edited bot long -> source user, bot_before.target ${ed.meta.bot_before?.target}, now ${ed.target}`);

// negative feedback on the zone with a note
const zoneCard = page.locator('.card[data-id]').first();
const zid = await zoneCard.getAttribute('data-id');
await zoneCard.locator('.fbnote').fill('האזור גבוה מדי');
await zoneCard.locator('.fbb[data-fb="zone"]').tap();
await page.waitForTimeout(300);
const st = await page.evaluate((zid) => ({
  z: window.__demoApi.drawings.find((d) => d.id === zid),
  c: window.__demoApi.commands[0], f: window.__demoApi.feedback[0],
}), zid);
ok(st.z.status === 'rejected', 'zone feedback -> bot zone rejected (stops counting)');
ok(st.c.kind === 'feedback' && st.c.text === '[feedback] zone: האזור גבוה מדי' && st.c.payload.category === 'zone'
  && st.c.payload.drawing_ids[0] === zid && st.c.payload.rule_version === 'v3d-2026-10-23' && st.c.payload.before.zone.zone_top === 98,
  'command row: kind feedback, text prefix, payload ' + JSON.stringify(st.c.payload));
ok(st.f && st.f.category === 'zone' && st.f.command_id === st.c.id, 'drawing_feedback row linked to the command');

// position feedback includes before/after of his edited long
await page.locator(`.card[data-id="${lid}"] .fbb[data-fb="position"]`).tap();
await page.waitForTimeout(300);
const c2 = await page.evaluate(() => window.__demoApi.commands[0]);
ok(c2.payload.category === 'position' && c2.payload.before.long.target === 118 && c2.payload.after.long.target === 120,
  'position feedback carries bot levels before + his edited levels after');

// the bot answers -> reply shown on the drawing card
await page.evaluate(() => {
  const a = window.__demoApi, c = a.commands.find((x) => x.payload?.category === 'zone');
  Object.assign(c, { status: 'done', reply: 'תוקן: אזור הוזז ל-93-95 (כלל v3e)', done_at: new Date().toISOString() });
  a.emit('commands', 'UPDATE', { ...c }, { id: c.id });
});
await page.waitForTimeout(300);
ok((await page.locator(`.card[data-id="${zid}"] .fbh`).textContent()).includes('תוקן: אזור הוזז'), 'bot reply shown on the drawing');
await page.locator(`.card[data-id="${zid}"] .fbh`).scrollIntoViewIfNeeded();
await page.waitForTimeout(2600);
await page.screenshot({ path: `${OUT}/13_feedback.png` });
console.log('     shot', `${OUT}/13_feedback.png`);
ok(errors.length === 0, 'no console errors ' + JSON.stringify(errors));
await browser.close();
