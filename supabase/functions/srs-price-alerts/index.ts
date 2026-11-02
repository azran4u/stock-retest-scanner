// Real-time price alerts to Telegram (stock-retest-scanner, Eyal 2026-11-02).
// pg_cron (job 'srs-price-alerts', every 10 min Mon-Fri 13-21 UTC) POSTs here with header x-srs-cron (Vault secret).
// For every ticker starred in the app (public.watchlist): entry level = Eyal's own Long (drawings kind 'long', source
// user/tv), else the expert trade (app-data/expert_zones.json), else the bot's Long. Quotes: Yahoo chart API (5m bars,
// regular session high/low). Alerts: 'near' (within 0.25 weekly ATR) and 'touch' (session range reached the entry),
// at most one per type / ticker / NY trading day (public.price_alerts unique key).
// Telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from function secrets, else Supabase Vault. Missing -> dry-run (logged).
// Manual: POST ?dry=1 (never sends) &force=1 (ignore market hours) &tickers=A,B  -> JSON with the messages.
import { createClient } from 'npm:@supabase/supabase-js@2';
import { classify, earningsNote, marketOpen, message, nyClock, pickLevel, type Level, type Quote } from './logic.ts';

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
    let tickers = ((await sb.from('watchlist').select('ticker')).data || []).map((r: any) => String(r.ticker));
    const only = u.searchParams.get('tickers'); if (only) tickers = only.split(',').map((s) => s.trim().toUpperCase());
    const { data: longs } = await sb.from('drawings').select('ticker,source,entry,stop,target,updated_at')
      .in('ticker', tickers).eq('kind', 'long').not('status', 'in', '(deleted,rejected,obsolete)');
    const [ez, earn] = [await readJson('expert_zones.json'), await readJson('earnings.json')];
    const levels = tickers.map((t) => pickLevel(t, (longs || []).filter((d: any) => d.ticker === t), ez?.tickers?.[t])).filter(Boolean) as Level[];
    const { data: done } = await sb.from('price_alerts').select('ticker,kind').eq('trade_day', clock.date).eq('live', live);
    const sent = new Set((done || []).map((r: any) => `${r.ticker}:${r.kind}`));
    const errors: string[] = [], out: any[] = [], checked: any[] = [];
    await pool(levels, 6, async (l) => {
      let q: Quote | null = null;
      try { q = await quote(l.ticker, clock.date); } catch (e) { errors.push(String(e)); return; }
      if (!q) { checked.push({ t: l.ticker, note: 'no quote today' }); return; }
      const c = classify(l, q);
      checked.push({ t: l.ticker, price: q.price, lo: q.dayLow, hi: q.dayHigh, entry: l.entry, src: l.src, dist_atr: c.distAtr, touch: c.touch, near: c.near });
      const kind = c.touch ? 'touch' : c.near ? 'near' : null;
      if (!kind || sent.has(`${l.ticker}:${kind}`) || (kind === 'near' && sent.has(`${l.ticker}:touch`))) return;
      const text = message(kind, l, q, c.distAtr, earningsNote(earn?.[l.ticker], clock.date), c.crossed);
      let tg: any = null;
      if (live) {
        const r = await fetch(`https://api.telegram.org/bot${botTok}/sendMessage`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: chat, text, disable_web_page_preview: true }) });
        tg = await r.json().catch(() => ({ ok: false })); if (!tg?.ok) { errors.push(`telegram ${l.ticker}: ${tg?.description || r.status}`); return; }
        tg = { ok: true, message_id: tg.result?.message_id };
      } else console.log('[dry-run]\n' + text);
      if (!dryParam || !force) {      // manual dry tests (?dry=1&force=1) do not consume the daily slot
        const { error } = await sb.from('price_alerts').insert({ ticker: l.ticker, kind, trade_day: clock.date, live, price: q.price, entry: l.entry,
          stop: l.stop, target: l.target, rr: l.rr, dist_atr: c.distAtr, source: l.src, message: text, telegram: tg });
        if (error && !String(error.message).includes('duplicate')) errors.push('insert ' + error.message);
      }
      out.push({ ticker: l.ticker, kind, live, text });
    });
    await status({ mode, checked: checked.length, sent: out.filter((x) => x.live).length, note: `${out.length} alert(s)`, error: errors.join('; ').slice(0, 500) || null });
    return json({ ny: clock, market: mk.why, mode, tickers: tickers.length, levels: levels.length, alerts: out, checked, errors });
  } catch (e) {
    await status({ mode, error: String(e).slice(0, 500) });
    return json({ error: String(e) }, 500);
  }
});
