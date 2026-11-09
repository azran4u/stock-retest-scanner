// Real-time price alerts to Telegram (stock-retest-scanner, Eyal 2026-11-02).
// pg_cron (job 'srs-price-alerts', every 10 min Mon-Fri 13-21 UTC) POSTs here with header x-srs-cron (Vault secret).
// Tracked: starred tickers (public.watchlist) + the hot list (app-data/expert_watch.json). Setup = Eyal's own Long / zone
// (drawings source user / tv = his override) else the expert trade / zone (app-data/expert_zones.json). Quotes: Yahoo
// chart API (5m bars). ACTIONABLE alerts only (Eyal 2026-11-02): 'limit' (place a buy limit / buy-stop at the entry),
// 'triggered' (filled today, still <= 0.5 ATR above), 'cancel' (setup broke while an order may be working).
// Falling knife (Eyal 2026-11-09): index.json f_no_red_vol_week === false -> no limit / triggered until the next weekly close. Rules in
// logic.ts decide() and supabase/README.md. Once per type / ticker / NY day + a cross-day cooldown per level.
// Telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from function secrets, else Supabase Vault. Missing -> dry-run (logged).
// Manual: POST ?dry=1 (never sends) &force=1 (ignore market hours) &tickers=A,B  -> JSON with the messages.
import { createClient } from 'npm:@supabase/supabase-js@2';
import { buildSetup, coolingDown, decide, earningsBlock, hadOrder, marketOpen, message, nyClock, type Quote, type Setup } from './logic.ts';

const sb = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b, null, 1), { status, headers: { 'Content-Type': 'application/json; charset=utf-8' } });
const secret = async (n: string) => Deno.env.get(n) || ((await sb.rpc('srs_alert_secret', { n })).data as string | null) || null;

async function readJson(path: string): Promise<any> {
  const { data, error } = await sb.storage.from('app-data').download(path);
  if (error || !data) return null;
  return JSON.parse(await data.text());
}

async function quote(t: string, day: string): Promise<Quote | null> {
  const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(t)}?interval=5m&range=1d`,
    { headers: { 'User-Agent': 'Mozilla/5.0 (srs-price-alerts)' } });
  if (!r.ok) throw new Error(`yahoo ${t} ${r.status}`);
  const res = (await r.json())?.chart?.result?.[0];
  const m = res?.meta; if (!m?.regularMarketPrice) return null;
  // only today's regular-session 5m bars (range=1d is the latest session; skip a stale session before the open)
  const ts: number[] = res.timestamp || [], q = res.indicators?.quote?.[0] || {};
  let hi = -Infinity, lo = Infinity, n = 0;
  ts.forEach((s, i) => {
    const d = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date(s * 1000));
    if (d !== day || q.high?.[i] == null || q.low?.[i] == null) return;
    hi = Math.max(hi, q.high[i]); lo = Math.min(lo, q.low[i]); n++;
  });
  const mday = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date((m.regularMarketTime || 0) * 1000));
  if (mday !== day && !n) return null;                         // no trade yet today
  return { price: m.regularMarketPrice, dayHigh: n ? Math.max(hi, m.regularMarketDayHigh ?? hi) : m.regularMarketDayHigh,
           dayLow: n ? Math.min(lo, m.regularMarketDayLow ?? lo) : m.regularMarketDayLow, prevClose: m.chartPreviousClose ?? m.previousClose ?? null };
}

async function pool<T, R>(xs: T[], k: number, f: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(xs.length); let i = 0;
  await Promise.all(Array.from({ length: Math.min(k, xs.length) }, async () => { while (i < xs.length) { const j = i++; out[j] = await f(xs[j]); } }));
  return out;
}

Deno.serve(async (req: Request) => {
  const u = new URL(req.url);
  if (u.searchParams.get('setup') === 'telegram') {   // box -> Vault: {"token": "...", "chat_id": "..."}, auth = nightly upload token
    const up = req.headers.get('x-srs-token') || '';
    const { data: good } = up ? await sb.rpc('srs_check_upload_token', { t: up }) : { data: false };
    if (!good) return json({ error: 'unauthorized' }, 401);
    const b = await req.json().catch(() => ({}));
    const set: string[] = [];
    for (const [k, n] of [['token', 'TELEGRAM_BOT_TOKEN'], ['chat_id', 'TELEGRAM_CHAT_ID']] as const) {
      if (b?.[k] == null || b[k] === '') continue;
      const { error } = await sb.rpc('srs_alert_set_secret', { n, v: String(b[k]) });
      if (error) return json({ error: error.message }, 500);
      set.push(n);
    }
    const t = await secret('TELEGRAM_BOT_TOKEN');
    const me = t ? await (await fetch(`https://api.telegram.org/bot${t}/getMe`)).json().catch(() => null) : null;
    return json({ set, bot: me?.ok ? me.result.username : null });
  }
  const tok = req.headers.get('x-srs-cron') || '';
  const want = await secret('srs_alert_cron_token');
  if (!tok || !want || tok !== want) return json({ error: 'unauthorized' }, 401);
  const force = u.searchParams.get('force') === '1', dryParam = u.searchParams.get('dry') === '1';
  const clock = nyClock(new Date()), mk = marketOpen(clock);
  const status = async (o: Record<string, unknown>) => { await sb.from('alert_runs').upsert({ id: 1, last_run: new Date().toISOString(), market: mk.why, ...o }); };
  if (!mk.open && !force) { await status({ note: 'skipped: ' + mk.why }); return json({ skipped: mk.why, ny: clock }); }

  const [botTok, chat] = [await secret('TELEGRAM_BOT_TOKEN'), await secret('TELEGRAM_CHAT_ID')];
  const live = !!(botTok && chat) && !dryParam;
  const mode = live ? 'live' : (botTok ? (chat ? 'dry (manual)' : 'dry (waiting for /start)') : 'dry (no token)');
  try {
    const starred = new Set(((await sb.from('watchlist').select('ticker')).data || []).map((r: any) => String(r.ticker)));
    const [ez, earn, hotDoc, idx] = [await readJson('expert_zones.json'), await readJson('earnings.json'), await readJson('expert_watch.json'), await readJson('index.json')];
    const hot = new Set(((hotDoc?.items || []) as any[]).map((x) => String(x.t)));
    let tickers = [...new Set([...starred, ...hot])].sort();
    const only = u.searchParams.get('tickers'); if (only) tickers = only.split(',').map((s) => s.trim().toUpperCase());
    const rowBy = new Map(((idx?.rows || []) as any[]).map((r) => [String(r.ticker), r]));
    const tf = (v: any) => (v === true || v === 'True' || v === 'true' ? true : v === false || v === 'False' || v === 'false' ? false : null);
    const { data: draws } = await sb.from('drawings').select('ticker,kind,source,entry,stop,target,zone_top,zone_bottom,updated_at')
      .in('ticker', tickers).in('source', ['user', 'tv']).in('status', ['active', 'approved', 'review']);
    const setups = tickers.map((t) => buildSetup(t, (draws || []).filter((d: any) => d.ticker === t), ez?.tickers?.[t],
      { starred: starred.has(t), hot: hot.has(t), uptrend: tf(rowBy.get(t)?.f_technical),
        knife: tf(rowBy.get(t)?.f_no_red_vol_week) === false })).filter(Boolean) as Setup[];
    const since = new Date(Date.now() - 35 * 86400000).toISOString().slice(0, 10);
    const { data: past } = await sb.from('price_alerts').select('ticker,kind,entry,stop,target,trade_day').eq('live', live).gte('trade_day', since).in('ticker', tickers);
    const pastBy = new Map<string, any[]>(); for (const r of past || []) pastBy.set(r.ticker, [...(pastBy.get(r.ticker) || []), r]);
    const errors: string[] = [], out: any[] = [], checked: any[] = [];
    await pool(setups, 6, async (s) => {
      let q: Quote | null = null;
      try { q = await quote(s.ticker, clock.date); } catch (e) { errors.push(String(e)); return; }
      if (!q) { checked.push({ t: s.ticker, note: 'no quote today' }); return; }
      const recent = pastBy.get(s.ticker) || [];
      const eb = earningsBlock(earn?.[s.ticker], clock.date);
      const d = decide(s, q, eb, hadOrder(s, recent));
      checked.push({ t: s.ticker, src: s.src, price: q.price, lo: q.dayLow, entry: s.entry, sl: s.stop, rr: s.rr, dist_atr: d.distAtr, kind: d.kind, why: d.why });
      if (!d.kind) return;
      if (recent.some((r) => r.kind === d.kind && String(r.trade_day).slice(0, 10) === clock.date)) return;   // once per type / day
      if (coolingDown(d.kind, s, recent, clock.date)) { checked[checked.length - 1].why += ' (cooldown)'; return; }
      const text = message(d.kind, s, q, d, s.uptrend == null ? 'מגמה: אין נתון בדוח' : null);
      let tg: any = null;
      if (live) {
        const r = await fetch(`https://api.telegram.org/bot${botTok}/sendMessage`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: chat, text, disable_web_page_preview: true }) });
        tg = await r.json().catch(() => ({ ok: false })); if (!tg?.ok) { errors.push(`telegram ${s.ticker}: ${tg?.description || r.status}`); return; }
        tg = { ok: true, message_id: tg.result?.message_id };
      } else console.log('[dry-run]\n' + text);
      if (!dryParam) {      // manual dry tests (?dry=1) never consume a slot / cooldown
        const { error } = await sb.from('price_alerts').insert({ ticker: s.ticker, kind: d.kind, trade_day: clock.date, live, price: q.price, entry: s.entry,
          stop: s.stop, target: s.target, rr: s.rr, dist_atr: d.distAtr, source: s.src, message: text, telegram: tg });
        if (error && !String(error.message).includes('duplicate')) errors.push('insert ' + error.message);
      }
      out.push({ ticker: s.ticker, kind: d.kind, live, text });
    });
    await status({ mode, checked: checked.length, sent: out.filter((x) => x.live).length, note: `${out.length} alert(s) · ${starred.size} starred + ${hot.size} hot`, error: errors.join('; ').slice(0, 500) || null });
    return json({ ny: clock, market: mk.why, mode, tickers: tickers.length, setups: setups.length, alerts: out, checked, errors });
  } catch (e) {
    await status({ mode, error: String(e).slice(0, 500) });
    return json({ error: String(e) }, 500);
  }
});
