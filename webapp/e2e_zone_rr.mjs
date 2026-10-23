// Zone edit -> bot Long follows -> live R:R / PASS (Eyal 2026-10-23), demo mode. Usage: node e2e_zone_rr.mjs [baseURL] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const BASE = process.argv[2] || 'http://localhost:4173/stock-retest-scanner/app/';
const OUT = process.argv[3] || '/workspace/app_shots';
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: 'he-IL' });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
await page.goto(BASE + '?demo=1');
await page.waitForSelector('.row');

// a ticker whose exported gates pass, with candles; give it a bot zone + bot Long with R:R 3
const setup = await page.evaluate(async () => {
  const { S, api, botLongFromZone, loadDaily } = window.__srs;
  const r = S.rows.find((x) => x.has_candles && x.f_dollar_vol === true && x.f_history === true && x.f_no_earnings_14d === true && x.f_no_red_vol_week !== false);
  const t = r.ticker;
  for (const d of [...S.drawings.values()]) if (d.ticker === t) S.drawings.delete(d.id);
  const daily = await loadDaily(t);
  const last = daily[daily.length - 1].close;
  const zt = Math.round(last * 0.92 * 100) / 100, zb = Math.round(last * 0.9 * 100) / 100;
  const b = botLongFromZone(daily, zb, zt);
  const tp = Math.round((b.entry + 3 * (b.entry - b.stop)) * 100) / 100;
  const z = await api.insertDrawing({ ticker: t, kind: 'zone', zone_top: zt, zone_bottom: zb, source: 'bot', status: 'active' });
  const l = await api.insertDrawing({ ticker: t, kind: 'long', entry: b.entry, stop: b.stop, target: tp, source: 'bot', status: 'active' });
  S.drawings.set(z.id, z); S.drawings.set(l.id, l);
  return { t, zt, zb, tp, entry: b.entry, stop: b.stop, atrw: b.atr_w, zid: z.id, lid: l.id };
});
console.log('     setup', JSON.stringify(setup));
const live = () => page.evaluate((t) => { const { S, liveOf } = window.__srs; return liveOf(S.byT.get(t)); }, setup.t);
ok((await live()).status !== 'FAIL', `${setup.t}: bot Long R:R 3 -> ${(await live()).status}`);

await page.goto(BASE + '?demo=1#/t/' + setup.t);
await page.waitForSelector(`.card[data-id="${setup.zid}"]`);
await page.waitForTimeout(500);
const hdr = () => page.locator('#tkb').textContent();
ok(/PASS|ממתינה/.test(await hdr()), `header before: ${await hdr()}`);

const setZone = async (top, bottom) => {
  const c = page.locator(`.card[data-id="${setup.zid}"]`);
  for (const [f, v] of top >= setup.zt ? [['zone_top', top], ['zone_bottom', bottom]] : [['zone_bottom', bottom], ['zone_top', top]]) {
    const i = c.locator(`input[data-f="${f}"]`);
    await i.fill(String(v)); await i.dispatchEvent('change');
    await page.waitForTimeout(250);
  }
  await page.locator('#tk').click(); // blur -> panel re-render
  await page.waitForTimeout(400);
};
// move the zone up close to TP: the bot Long follows, R:R drops below 2
const up = Math.round((setup.tp - 1.4 * setup.atrw) * 100) / 100;
await setZone(up, Math.round((up - (setup.zt - setup.zb)) * 100) / 100);
const lg = await page.evaluate((id) => window.__srs.S.drawings.get(id), setup.lid);
ok(lg.entry > setup.entry && lg.target === setup.tp && lg.source === 'bot' && lg.meta?.zone_follow, `bot Long followed: entry ${setup.entry} -> ${lg.entry}, SL ${setup.stop} -> ${lg.stop}, TP kept ${lg.target}`);
const l2 = await live();
ok(l2.status === 'FAIL' && l2.rr < 2, `R:R ${l2.rr?.toFixed(2)} < 2 -> ${l2.status}`);
ok(/FAIL · R:R \d+\.\d\d < 2/.test(await hdr()) && !/PASS/.test(await hdr()), `header: ${await hdr()}`);
ok(await page.locator('.rr-box').count() === 1, 'stock page explains: לא ב-PASS · R:R < 2');
await page.screenshot({ path: `${OUT}/30_zone_rr_fail.png`, fullPage: true });
await page.evaluate(() => { location.hash = '#/'; });
await page.waitForSelector('.list');
await page.click('.chip[data-chip="pass"]'); await page.waitForTimeout(300);
ok(await page.locator(`.row[data-t="${setup.t}"]`).count() === 0, 'row left the PASS list');
await page.click('.chip[data-chip="all"]'); await page.fill('#q', setup.t); await page.waitForTimeout(300);
ok(/FAIL · R:R/.test(await page.locator(`.row[data-t="${setup.t}"] .r2`).textContent()), 'list row shows FAIL · R:R x < 2');
await page.fill('#q', ''); await page.waitForTimeout(200);

// back to the original zone -> PASS again
await page.goto(BASE + '?demo=1#/t/' + setup.t);
await page.waitForSelector(`.card[data-id="${setup.zid}"]`);
await setZone(setup.zt, setup.zb);
const l3 = await live();
ok(l3.status !== 'FAIL' && l3.rr >= 2, `zone back: R:R ${l3.rr?.toFixed(2)} -> ${l3.status}`);
ok(/PASS|ממתינה/.test(await hdr()), `header after: ${await hdr()}`);

// his own Long does not move: only its R:R is re-checked
const own = await page.evaluate(async (s) => {
  const { S, api } = window.__srs;
  const l = S.drawings.get(s.lid); l.source = 'user'; await api.updateDrawing(s.lid, { source: 'user' });
  return { entry: l.entry, stop: l.stop };
}, setup);
await setZone(up, Math.round((up - (setup.zt - setup.zb)) * 100) / 100);
const lg2 = await page.evaluate((id) => window.__srs.S.drawings.get(id), setup.lid);
ok(lg2.entry === own.entry && lg2.stop === own.stop, `his Long not moved (${lg2.entry} / ${lg2.stop})`);
ok((await live()).status !== 'FAIL', 'his Long R:R unchanged -> still PASS');
// no Long -> R:R unknown -> not PASS
await page.evaluate((id) => { const { S } = window.__srs; S.drawings.delete(id); }, setup.lid);
await setZone(setup.zt, setup.zb);
const l4 = await live();
ok(l4.status === 'FAIL' && l4.rr == null && /אין לונג/.test(await hdr()), `no Long -> ${l4.status} (${l4.why})`);
ok(errors.length === 0, `no page errors ${JSON.stringify(errors)}`);
await browser.close();
